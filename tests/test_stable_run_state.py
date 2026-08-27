"""Regression tests for durable subtitle-run state and safe resume planning."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from app.core.subtitle_processor.stable_run_state import (
    StableRunStateStore,
    build_stable_run_fingerprint,
    format_stage_progress,
)
from app.core.subtitle_processor.stable_pipeline_contracts import (
    canonical_word_ledger_hash,
)
from app.core.article_context import (
    ARTICLE_ANALYSIS_META_KEY,
    ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
    ARTICLE_ASR_CORRECTION_POLICY_VERSION,
    article_analysis_cache_key,
    article_analysis_prompt_hash,
    article_text_hash,
)
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.thread.subtitle_thread import SubtitleThread
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor
from app.core.subtitle_processor.authoritative_parent_chinese import (
    build_authoritative_parent_chinese_artifact,
)


class _Config:
    llm_model = "deepseek-v4-flash"
    screen_subtitle_full_translation_model = "deepseek-v4-pro"
    screen_subtitle_allocation_review_model = "deepseek-v4-flash"
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
    screen_subtitle_allocation_max_concurrency = 2
    screen_subtitle_allocation_batch_size = 16
    screen_subtitle_translation_request_budget = 40
    screen_subtitle_translation_request_max_attempts = 3
    custom_prompt_text = ""


def _fingerprint(source: Path, **changes):
    values = {
        "article_reference_text": "Reference article.",
        "article_context_data": {"title": "Reference"},
        "use_article_reference_assist": True,
        "use_article_translation_terms": True,
        "alignment_backend": "whisperx-time-only",
        "custom_prompt_text": "",
        "article_analysis_prompt_policy_version": ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
        "article_analysis_prompt_sha256": article_analysis_prompt_hash(),
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


def _write_frozen_parent_checkpoint(root: Path) -> Path:
    artifact_dir = root / "stable-artifacts"
    artifact_dir.mkdir()
    words = [
        {
            "word_id": 0,
            "surface": "Hello",
            "normalized": "hello",
            "start_ms": 100,
            "end_ms": 400,
            "alignment_source": "whisperx",
            "source_segment_ids": [1],
        },
        {
            "word_id": 1,
            "surface": "world.",
            "normalized": "world",
            "start_ms": 450,
            "end_ms": 900,
            "alignment_source": "whisperx",
            "source_segment_ids": [2],
        },
    ]
    ledger_hash = canonical_word_ledger_hash(words)
    parent_authority = build_authoritative_parent_chinese_artifact(
        [
            {
                "subtitle_id": "S0001",
                "english": "Hello world.",
                "chinese": "你好，世界。",
                "word_start": 0,
                "word_end": 1,
                "provenance": {
                    "kind": "automatic",
                    "producer": "fixed_id_allocation",
                    "base_record_hash": "",
                    "display_page_contract_hash": "",
                },
            }
        ],
        source_word_ledger_hash=ledger_hash,
        producer="stable_parent_chinese",
    )
    payloads = {
        "run-manifest.json": {
            "pipeline": "screen_subtitle_stable",
            "prompt_version": "global-subtitle-id-v2",
            "model": "deepseek-v4-flash",
            "full_translation_model": "deepseek-v4-pro",
            "allocation_review_model": "deepseek-v4-flash",
            "target_language": "简体中文",
            "max_cjk_chars": 24,
            "max_english_words": 16,
            "frozen_subtitle_ids": ["S0001"],
        },
        "word-ledger.json": {
            "schema_version": 2,
            "hash": ledger_hash,
            "words": words,
        },
        "subtitle-spans.json": [
            {
                "subtitle_id": "S0001",
                "source_ids": [1, 2],
                "word_start": 0,
                "word_end": 1,
                "original": "Hello world.",
                "translated": "你好，世界。",
            }
        ],
        "translations.json": [
            {
                "subtitle_id": "S0001",
                "start_ms": 80,
                "end_ms": 950,
                "text": "Hello world.",
                "translated_text": "你好，世界。",
            }
        ],
        "semantic-groups.json": [
            {
                "group_id": 1,
                "start_index": 0,
                "expected_subtitle_ids": ["S0001"],
                "full_english": "Hello world.",
                "subtitle_parts": [{"subtitle_id": "S0001"}],
            }
        ],
        "transcript.json": [
            {
                "id": 1,
                "start_ms": 100,
                "end_ms": 400,
                "text": "Hello",
                "translated_text": "",
            },
            {
                "id": 2,
                "start_ms": 450,
                "end_ms": 900,
                "text": " world.",
                "translated_text": "",
            },
        ],
        "final-cue-timeline.json": {
            "schema_version": 1,
            "expected_subtitle_ids": ["S0001"],
            "records": [
                {
                    "subtitle_id": "S0001",
                    "word_start": 0,
                    "word_end": 1,
                    "word_envelope_start_ms": 100,
                    "word_envelope_end_ms": 900,
                    "start_ms": 80,
                    "end_ms": 950,
                }
            ],
            "validation": {"status": "PASS", "error_count": 0, "errors": []},
            "alignment": {
                "requested_backend": "whisperx-time-only",
                "applied_backend": "whisperx-time-only",
            },
        },
        "display-boundary-evidence.json": {
            "schema_version": 1,
            "policy_version": "formal-boundary-evidence-v1",
            "word_ledger_hash": ledger_hash,
            "boundaries": {
                "1": {
                    "hard_issues": [],
                    "soft_issues": [],
                    "boundary_score": 0.0,
                    "protected_syntax": False,
                    "pause_ms": 50,
                }
            },
        },
        "stable-boundary-snapshots.json": {
            "schema_version": 1,
            "word_ledger_hash": ledger_hash,
            "max_english_words": 16,
            "stages": [
                {
                    "stage": "final_frozen_ids",
                    "boundaries": [],
                }
            ],
            "changes": [{"stage": "final_frozen_ids", "changed": False}],
            "pre_id_boundary_repairs": [{"repair_reason": "fixture"}],
        },
        "authoritative-parent-chinese.json": parent_authority,
    }
    for name, payload in payloads.items():
        (artifact_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return artifact_dir


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

        changed_article_policy = _fingerprint(
            source,
            article_analysis_prompt_policy_version="article-context-analysis-test-version",
        )
        assert not StableRunStateStore(root).plan_resume(changed_article_policy).compatible

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

        class ChangedFullTranslationModelConfig(_Config):
            screen_subtitle_full_translation_model = "different-pro-model"

        changed_full_translation_model = build_stable_run_fingerprint(
            subtitle_path=source,
            subtitle_config=ChangedFullTranslationModelConfig(),
            article_reference_text="Reference article.",
            article_context_data={"title": "Reference"},
            use_article_reference_assist=True,
            use_article_translation_terms=True,
            alignment_backend="whisperx-time-only",
        )
        assert not StableRunStateStore(root).plan_resume(
            changed_full_translation_model
        ).compatible


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


def test_frozen_parent_checkpoint_restores_fixed_ids_words_and_final_timeline():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = _write_frozen_parent_checkpoint(Path(temp_dir))
        editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
        editor.enable_stable_mode = True
        editor.model = "deepseek-v4-flash"
        editor.full_translation_model = "deepseek-v4-pro"
        editor.allocation_review_model = "deepseek-v4-flash"
        editor.display_page_translation_model = "deepseek-v4-flash"
        editor.target_language = "简体中文"
        editor.max_cjk_chars = 24
        editor.max_english_words = 16
        editor.coverage_report_path = ""

        restored = editor.restore_frozen_parent_checkpoint(artifact_dir)

        assert [segment.text for segment in restored.segments] == ["Hello world."]
        assert [segment.translated_text for segment in restored.segments] == [
            "你好，世界。"
        ]
        assert [segment.subtitle_id for segment in restored.segments] == ["S0001"]
        assert [(segment.start_time, segment.end_time) for segment in restored.segments] == [
            (80, 950)
        ]
        assert editor._frozen_subtitle_ids == ["S0001"]
        assert len(editor._active_word_entries) == 2
        assert editor._final_cue_timeline["validation"]["status"] == "PASS"
        assert editor._boundary_snapshots[0]["stage"] == "final_frozen_ids"
        assert editor._boundary_snapshot_changes[0]["changed"] is False
        assert editor._pre_id_boundary_repairs[0]["repair_reason"] == "fixture"


def test_frozen_parent_checkpoint_rejects_timeline_word_span_drift():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = _write_frozen_parent_checkpoint(Path(temp_dir))
        timeline_path = artifact_dir / "final-cue-timeline.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["records"][0]["word_end"] = 0
        timeline_path.write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
        editor.enable_stable_mode = True
        editor.model = "deepseek-v4-flash"
        editor.full_translation_model = "deepseek-v4-pro"
        editor.allocation_review_model = "deepseek-v4-flash"
        editor.display_page_translation_model = "deepseek-v4-flash"
        editor.target_language = "简体中文"
        editor.max_cjk_chars = 24
        editor.max_english_words = 16
        editor.coverage_report_path = ""

        try:
            editor.restore_frozen_parent_checkpoint(artifact_dir)
        except RuntimeError as exc:
            assert "word span" in str(exc)
        else:
            raise AssertionError("timeline word-span drift must reject checkpoint reuse")


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


def test_display_page_progress_uses_its_own_stage_and_batch_count():
    class _Progress:
        def __init__(self):
            self.events = []

        def emit(self, *args):
            self.events.append(args)

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.progress = _Progress()
    thread.tr = lambda value: value
    thread._run_state_store = None
    thread._last_progress_value = 96
    thread._active_stage = "display_page_translation"
    thread._active_stage_started_at = time.perf_counter()
    thread._screen_editor_phase_started_at = {}

    thread._handle_screen_editor_progress(
        {
            "phase": "display_page_translation",
            "completed": 1,
            "total": 2,
            "cache_hits": 0,
            "retries": 1,
            "active_batches": 1,
        }
    )

    assert thread.progress.events[-1][0] == 97
    assert "双语分页语义分配" in thread.progress.events[-1][1]
    assert "第 1/2 批" in thread.progress.events[-1][1]


def test_frozen_parent_checkpoint_progress_does_not_finish_downstream_stages():
    class _Progress:
        def __init__(self):
            self.events = []

        def emit(self, *args):
            self.events.append(args)

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.progress = _Progress()
    thread.tr = lambda value: value
    thread._run_state_store = None
    thread._last_progress_value = 96
    thread._active_stage = "frozen_parent_timeline"
    thread._active_stage_started_at = time.perf_counter()

    thread._emit_stage_progress(
        "frozen_parent_timeline",
        "已复用父字幕检查点",
        fraction=1.0,
    )

    assert thread.progress.events[-1][0] == 96


def test_resume_recomputes_only_stale_article_asr_correction_policy():
    class _ResumePlan:
        @staticmethod
        def can_reuse(stage):
            return stage in {"article_context", "article_asr_correction"}

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        article_text = "Reference article."
        (root / "article_context.json").write_text(
            json.dumps(
                {
                    "title": "Reference",
                    ARTICLE_ANALYSIS_META_KEY: {
                        "article_text_hash": article_text_hash(article_text),
                        "prompt_hash": article_analysis_prompt_hash(),
                        "analysis_prompt_hash": article_analysis_prompt_hash(),
                        "analysis_prompt_policy_version": ARTICLE_ANALYSIS_PROMPT_POLICY_VERSION,
                        "analysis_cache_key": article_analysis_cache_key(article_text),
                    },
                }
            ),
            encoding="utf-8",
        )
        corrected = ASRData([ASRDataSeg("Ms Hao", 100, 500)])
        (root / "asr_corrected.json").write_text(
            json.dumps(corrected.to_json(), ensure_ascii=False),
            encoding="utf-8",
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = type(
            "Task",
            (),
            {"article_reference_text": article_text},
        )()
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
    test_frozen_parent_checkpoint_restores_fixed_ids_words_and_final_timeline()
    test_frozen_parent_checkpoint_rejects_timeline_word_span_drift()
    test_progress_text_is_human_readable_and_signal_payload_remains_two_values()
    test_resume_recomputes_only_stale_article_asr_correction_policy()
    print("stable run state tests passed")
