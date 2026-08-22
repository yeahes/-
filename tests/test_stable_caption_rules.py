import sys
import json
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor, ScreenSubtitleItem
from app.core.subtitle_processor.final_cue_timeline import (
    DISPLAY_LEAD_IN_MS,
    DISPLAY_TAIL_PADDING_MS,
)
from app.core.subtitle_processor.stable_ts_alignment import (
    align_frozen_word_ledger_with_whisperx,
    _fallback_implausible_stable_ts_updates,
    _make_whisperx_word_segments,
)
from app.core.subtitle_processor.word_timing_trust import (
    find_implausible_word_timing_runs,
)
from app.core.subtitle_processor.stable_display_planner import (
    plan_word_page_spans,
    spans_cover_words,
)
from app.core.subtitle_processor.stable_display_page_contract import (
    build_display_page_contract,
    validate_page_translation_response,
)
from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.entities import (
    SynthesisConfig,
    SynthesisTask,
    SubtitleConfig,
    SubtitleTask,
    TargetLanguageEnum,
)
from app.core.task_factory import TaskFactory
from app.thread.subtitle_thread import SubtitleThread
from app.thread.video_synthesis_thread import VideoSynthesisThread, resolve_podcast_template_subtitle
from app.core.utils import podcast_learning_video
from tests.caption_audit.metrics import (
    CaptionCue,
    audit_srt,
    _chinese_semantic_group_issues,
    _syntax_boundary_reasons,
    split_bilingual_body,
    count_words,
)


def _editor(max_words=14):
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = max_words
    editor._syntax_protected_cuts = set()
    editor._syntax_hard_cut_issues = {}
    editor._syntax_nlp = None
    editor._active_word_entries = []
    editor.coverage_report_path = None
    editor.last_validation_summary = None
    editor._frozen_subtitle_ids = []
    editor._translation_structure_errors = []
    editor._last_llm_raw_returns = []
    editor._last_semantic_group_debug = []
    editor._last_allocation_inputs = []
    editor._last_allocation_raw_returns = []
    editor._last_allocation_validation = []
    editor._last_allocation_retry_log = []
    editor._last_allocation_final = []
    editor._last_allocation_unresolved = []
    editor._last_semantic_group_audit_contexts = {}
    editor._last_semantic_group_id_by_subtitle_id = {}
    editor._boundary_snapshots = []
    editor._boundary_snapshot_changes = []
    editor._boundary_snapshot_item_sets = {}
    editor._pre_id_boundary_repairs = []
    editor._qa_review_points_path = ""
    return editor


def _entries(text):
    entries = []
    current = 0
    for match in ScreenSubtitleEditor._word_token_matches(text):
        surface = match.group(0)
        tokens = ScreenSubtitleEditor._word_tokens(surface)
        token = tokens[0] if tokens else surface.lower()
        entries.append(
            {
                "token": token,
                "surface": surface,
                "start_time": current,
                "end_time": current + 180,
            }
        )
        current += 220
    return entries


def test_formal_boundary_audit_projects_display_pages_and_unresolved_pre_id_evidence():
    editor = _editor(max_words=16)
    editor._active_word_entries = _entries(
        "Today we explain this example clearly. Another simple sentence starts right here."
    )
    editor._last_subtitle_items = [
        ScreenSubtitleItem(
            [1],
            "Today we explain this example clearly.",
            "第一条",
            0,
            5,
            "S0001",
        ),
        ScreenSubtitleItem(
            [2], "Another simple sentence starts right here.", "第二条", 6, 11, "S0002"
        ),
    ]
    editor._display_boundary_evidence_artifact = {
        "boundaries": {
            "3": {
                "hard_issues": ["subject_finite_verb_split"],
                "soft_issues": [],
                "pause_ms": 80,
            }
        }
    }
    editor._display_page_translation_artifact = {
        "status": "PASS",
        "render_plans": [
            {
                "parent_subtitle_id": "S0001",
                "pages": [
                    {
                        "display_page_id": "S0001.P01",
                        "word_start": 0,
                        "word_end": 2,
                        "start_ms": 0,
                        "end_ms": 400,
                        "english": "Today we explain",
                        "boundary_before": {"classification": "allow", "issue_codes": []},
                    },
                    {
                        "display_page_id": "S0001.P02",
                        "word_start": 3,
                        "word_end": 5,
                        "start_ms": 400,
                        "end_ms": 800,
                        "english": "this example clearly.",
                        "boundary_before": {
                            "classification": "review",
                            "confidence": "high",
                            "issue_codes": ["subject_finite_verb_split"],
                        },
                    },
                ],
            }
        ],
    }
    editor._pre_id_boundary_repairs = [
        {
            "old_cut_word_index": [5, 6],
            "unresolved_hard_issue": True,
            "repair_attempted": True,
            "repair_succeeded": False,
            "repaired_by": "_validate_and_repair_final_pre_id_boundaries",
            "repair_reason": "unresolved_hard_issue",
            "hard_issues": ["right_orphaned_finite_predicate"],
        }
    ]
    segments = [
        ASRDataSeg("Today we explain this example clearly.", 0, 800, "第一条"),
        ASRDataSeg("Another simple sentence starts right here.", 800, 1200, "第二条"),
    ]
    for subtitle_id, word_start, word_end, segment in (
        ("S0001", 0, 5, segments[0]),
        ("S0002", 6, 11, segments[1]),
    ):
        segment.subtitle_id = subtitle_id
        segment.word_start = word_start
        segment.word_end = word_end

    payload = editor._english_boundary_audit_payload(segments)

    assert payload["schema_version"] == 2
    assert payload["summary"]["boundary_count"] == 2
    parent = next(record for record in payload["records"] if record["scope"] == "parent_cue")
    display = next(record for record in payload["records"] if record["scope"] == "display_page")
    assert parent["classification"] == "review"
    assert parent["confidence"] == "high"
    assert "right_orphaned_finite_predicate" in parent["rule_codes"]
    assert display["right_display_page_id"] == "S0001.P02"
    assert display["right_word_id"] == 3
    assert display["classification"] == "review"
    assert display["original_classification"] == "hard"
    assert "subject_finite_verb_split" in display["rule_codes"]


def _split_text(text, max_words=14):
    editor = _editor(max_words=max_words)
    editor._active_word_entries = _entries(text)
    ranges = editor._stable_word_ranges_for_span((0, len(editor._active_word_entries) - 1))
    return [
        " ".join(entry["surface"] for entry in editor._active_word_entries[start : end + 1])
        for start, end in ranges
    ]


def test_parent_boundary_gate_rejects_dependent_fragment_shapes_before_ids_freeze():
    cases = [
        (
            "And to understand just",
            "how wild that price tag really is, you really have to look closer.",
            "trailing_modifier_fragment",
        ),
        (
            "If every piece of that manufacturing puzzle is intrinsically Chinese,",
            "at what point does the assembled product become Vietnamese?",
            "open_subordinate_prefix_fragment",
        ),
        (
            "The imports came from a global trading system",
            "that America helped create in the 1940s.",
            "relative_clause_entrance_split",
        ),
        (
            "The company said it wasn't,",
            "you know, a legacy manufacturer with decades of experience.",
            "trailing_auxiliary_fragment",
        ),
    ]
    for left_text, right_text, expected_issue in cases:
        editor = _editor(max_words=16)
        editor._active_source_word_spans = {}
        editor._active_word_entries = _entries(f"{left_text} {right_text}")
        left_count = len(_entries(left_text))
        left = editor._item_from_word_span(0, left_count - 1)
        right = editor._item_from_word_span(
            left_count,
            len(editor._active_word_entries) - 1,
        )

        evaluation = editor._evaluate_item_pair_for_final_boundary(left, right)

        assert evaluation["legal"] is False
        assert expected_issue in evaluation["hard_issues"]


def test_parent_boundary_gate_keeps_preposition_led_continuation_reviewable():
    editor = _editor(max_words=16)
    editor._active_source_word_spans = {}
    editor._active_word_entries = _entries(
        "Revenue climbed to nearly 24 million in a difficult consumer market."
    )
    left = editor._item_from_word_span(0, 5)
    right = editor._item_from_word_span(6, len(editor._active_word_entries) - 1)

    evaluation = editor._evaluate_item_pair_for_final_boundary(left, right)

    assert evaluation["legal"] is True
    assert "leading_prepositional_fragment" in evaluation["soft_issues"]


def test_parent_boundary_gate_does_not_let_a_pause_legalize_dangling_syntax():
    editor = _editor(max_words=16)
    editor._active_source_word_spans = {}
    editor._active_word_entries = _entries(
        "The company said it wasn't a legacy manufacturer."
    )
    left = editor._item_from_word_span(0, 4)
    right = editor._item_from_word_span(5, len(editor._active_word_entries) - 1)
    editor._active_word_entries[5]["start_time"] = (
        editor._active_word_entries[4]["end_time"] + 900
    )

    evaluation = editor._evaluate_item_pair_for_final_boundary(left, right)

    assert evaluation["pause_ms"] == 900
    assert evaluation["legal"] is False
    assert "trailing_auxiliary_fragment" in evaluation["hard_issues"]


def test_complete_sentence_overflow_does_not_create_dangling_emphasis_boundary():
    parts = _split_text(
        "And to understand just how wild that price tag really is, you really "
        "have to look at how historically rare this behavior is.",
        max_words=16,
    )

    assert all(not part.rstrip(" ,").endswith(" just") for part in parts[:-1])
    assert " ".join(parts) == (
        "And to understand just how wild that price tag really is, you really "
        "have to look at how historically rare this behavior is."
    )


def test_final_time_alignment_reapplies_display_padding_to_loaded_short_subtitle():
    editor = _editor()
    segments = [
        ASRDataSeg("Previous line.", 0, 1000, "前一句。"),
        ASRDataSeg("over 20% of its real value.", 1200, 1320, "超过20%的实际价值。"),
        ASRDataSeg("Next line.", 2300, 3200, "下一句。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[1].end_time - repaired[1].start_time >= 700
    assert repaired[0].end_time <= repaired[1].start_time - 40
    assert repaired[1].end_time <= repaired[2].start_time - 40
    assert repaired[1].text == segments[1].text
    assert repaired[1].translated_text == segments[1].translated_text
    assert getattr(repaired[1], "subtitle_id") == "S0002"


def test_final_time_alignment_shifts_next_when_loaded_short_has_no_gap():
    editor = _editor()
    segments = [
        ASRDataSeg("deliver the joke,", 302600, 305840, "讲出笑话，"),
        ASRDataSeg(
            "and react to the silence if it completely bombs.",
            305880,
            306140,
            "并且在它彻底冷场时应对沉默。",
        ),
        ASRDataSeg("Right. You're on the hook for the delivery.", 306180, 307740, "没错，你要负责实际的表达。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[1].start_time == 305880
    assert repaired[1].end_time - repaired[1].start_time >= 700
    assert repaired[2].start_time >= repaired[1].end_time + 40
    assert repaired[2].end_time - repaired[2].start_time >= 700
    assert repaired[1].text == segments[1].text
    assert repaired[2].text == segments[2].text
    assert getattr(repaired[1], "subtitle_id") == "S0002"
    assert getattr(repaired[2], "subtitle_id") == "S0003"


def test_final_time_alignment_runs_chinese_speed_repair_without_touching_english():
    editor = _editor()
    asr_data = ASRData(
        [
            ASRDataSeg(
                "can't spell to save his life.",
                0,
                1560,
                "拼写烂到不行的人之手的文本所带来的恐怖谷效应说起。",
            )
        ]
    )
    asr_data.segments[0].subtitle_id = "S0001"
    editor._last_semantic_groups = [{"id": 1, "items": []}]
    editor._last_subtitle_items = []

    called = {}

    def fake_compress(segments, semantic_groups=None, subtitle_items=None):
        called["semantic_groups"] = semantic_groups
        return [
            editor._copy_segment(
                segments[0],
                translated_text="它来自一个平时拼写很差的人",
            )
        ]

    editor._compress_fast_chinese_segments = fake_compress
    editor._write_coverage_report = lambda *args, **kwargs: None

    repaired = editor.repair_after_final_time_alignment(asr_data)

    assert called["semantic_groups"] == editor._last_semantic_groups
    assert repaired.segments[0].text == "can't spell to save his life."
    assert getattr(repaired.segments[0], "subtitle_id") == "S0001"
    assert repaired.segments[0].translated_text == "它来自一个平时拼写很差的人"


def test_fixed_id_parent_chinese_sync_updates_only_the_chinese_projection():
    editor = _editor()
    editor._last_subtitle_items = [
        ScreenSubtitleItem(
            source_ids=[1],
            original="This is still the same English cue",
            translated="这仍是同一条中文字幕，",
            word_start=3,
            word_end=9,
            subtitle_id="S0001",
        )
    ]
    segment = ASRDataSeg(
        "This is still the same English cue",
        1000,
        2600,
        "这仍是同一条中文字幕",
    )
    segment.subtitle_id = "S0001"
    segment.word_start = 3
    segment.word_end = 9

    editor._sync_fixed_id_parent_chinese_state([segment])

    item = editor._last_subtitle_items[0]
    assert item.translated == segment.translated_text
    assert item.original == "This is still the same English cue"
    assert (item.word_start, item.word_end, item.subtitle_id) == (3, 9, "S0001")


def test_fixed_id_parent_chinese_sync_rejects_structural_drift_before_writing():
    editor = _editor()
    editor._last_subtitle_items = [
        ScreenSubtitleItem(
            source_ids=[1],
            original="Frozen English cue.",
            translated="同步前中文。",
            word_start=0,
            word_end=2,
            subtitle_id="S0001",
        )
    ]
    segment = ASRDataSeg("Changed English cue.", 0, 1000, "同步后中文。")
    segment.subtitle_id = "S0001"
    segment.word_start = 0
    segment.word_end = 2

    try:
        editor._sync_fixed_id_parent_chinese_state([segment])
    except RuntimeError as exc:
        assert "fixed_id_parent_chinese_sync_invalid" in str(exc)
    else:
        raise AssertionError("English drift must not be hidden by Chinese state sync")

    assert editor._last_subtitle_items[0].translated == "同步前中文。"


def test_final_time_alignment_publishes_punctuation_repair_to_fixed_id_items():
    editor = _editor()
    segment = ASRDataSeg(
        "This parent remains open",
        1000,
        2500,
        "这条父字幕仍未结束，",
    )
    segment.subtitle_id = "S0001"
    segment.word_start = 0
    segment.word_end = 3
    editor._last_subtitle_items = [
        ScreenSubtitleItem(
            source_ids=[1],
            original=segment.text,
            translated=segment.translated_text,
            word_start=segment.word_start,
            word_end=segment.word_end,
            subtitle_id=segment.subtitle_id,
        )
    ]
    editor._active_source_segments_by_id = {}
    editor._audit_final_display_coverage = lambda segments, source: list(segments)
    editor.refresh_final_cue_timeline_artifact = lambda segments: None
    editor._write_coverage_report = lambda *args, **kwargs: None
    editor._write_stable_pipeline_artifacts = lambda **kwargs: None

    repaired = editor.repair_after_final_time_alignment(
        ASRData([segment]),
        preserve_aligned_timing=True,
        allow_chinese_compression=False,
    )

    assert repaired.segments[0].translated_text == "这条父字幕仍未结束"
    assert editor._last_subtitle_items[0].translated == "这条父字幕仍未结束"


def test_blocked_checkpoint_timeline_skips_chinese_compression_api_work():
    editor = _editor()
    asr_data = ASRData([ASRDataSeg("Precisely.", 1000, 1120, "正是如此。")])
    asr_data.segments[0].subtitle_id = "S0001"
    editor._last_semantic_groups = [{"id": 1, "items": []}]
    editor._last_subtitle_items = []
    editor._compress_fast_chinese_segments = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("blocked checkpoint must not run Chinese compression")
    )
    editor._write_coverage_report = lambda *args, **kwargs: None

    repaired = editor.repair_after_final_time_alignment(
        asr_data,
        allow_chinese_compression=False,
    )

    assert repaired.segments[0].text == "Precisely."
    assert repaired.segments[0].translated_text == "正是如此。"


def test_final_time_alignment_checks_chinese_speed_against_final_timeline_duration():
    editor = _editor()
    asr_data = ASRData(
        [
            ASRDataSeg(
                "A fixed English cue.",
                0,
                1000,
                "这是一条在最终时长收紧后会超速的中文字幕",
            )
        ]
    )
    asr_data.segments[0].subtitle_id = "S0001"
    editor._last_semantic_groups = []
    editor._last_subtitle_items = []
    editor._align_segment_translation_punctuation = lambda segments: list(segments)
    editor._report_subtitle_coverage_gaps = lambda *args, **kwargs: None
    editor._write_stable_pipeline_artifacts = lambda **kwargs: None

    observed = {}

    def compress(segments, **kwargs):
        observed["duration_ms"] = segments[0].end_time - segments[0].start_time
        return list(segments)

    editor._audit_final_display_coverage = lambda segments, source: list(segments)
    editor._compress_fast_chinese_segments = compress

    repaired = editor.repair_after_final_time_alignment(
        asr_data,
        preserve_aligned_timing=True,
    )

    assert observed["duration_ms"] == 1000
    assert repaired.segments[0].end_time == 1000
    assert repaired.segments[0].text == "A fixed English cue."
    assert repaired.segments[0].subtitle_id == "S0001"


def test_chinese_compression_inherits_terminal_punctuation():
    editor = _id_editor()
    segment = ASRDataSeg(
        "A complete sentence.",
        0,
        1000,
        "这是一条较长的完整中文字幕。",
    )
    segment.subtitle_id = "S0001"

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={"items": [{"subtitle_id": "S0001", "chinese": "这是简洁完整表达"}]},
    ):
        repaired = editor._compress_fast_chinese_segments([segment])

    assert repaired[0].translated_text == "这是简洁完整表达。"


def test_chinese_compression_accepts_punctuated_sentence_outside_action_whitelist():
    editor = _id_editor()
    segment = ASRDataSeg(
        "We've talked a lot about how they're building it distantly.",
        0,
        1872,
        "我们已经谈了很多他们是如何以迂回的方式构建它的。",
    )
    segment.subtitle_id = "S0001"
    context = {
        "group_id": 1,
        "full_english": segment.text,
        "full_translation": segment.translated_text,
        "parts": [
            {
                "index": 0,
                "subtitle_id": segment.subtitle_id,
                "english": segment.text,
                "current_chinese": segment.translated_text,
                "duration_ms": 1872,
            }
        ],
    }
    candidate = "我们详谈了他们迂回建造的方式。"

    assert not editor._is_incomplete_chinese_group(candidate)
    assert editor._is_valid_chinese_compression(
        candidate,
        segment,
        [segment],
        0,
        context=context,
    )


def test_single_cue_speed_compression_does_not_use_allocation_coverage_as_a_veto():
    editor = _id_editor()
    segment = ASRDataSeg(
        "We've talked a lot about how they're building it distantly.",
        0,
        1872,
        "我们已经谈了很多他们是如何以迂回的方式构建它的。",
    )
    segment.subtitle_id = "S0001"
    item = ScreenSubtitleItem(
        source_ids=[1],
        original=segment.text,
        translated=segment.translated_text,
        word_start=0,
        word_end=9,
        subtitle_id=segment.subtitle_id,
    )
    editor._last_semantic_full_translations = {1: segment.translated_text}
    groups = [{"id": 1, "start_index": 0, "items": [item]}]

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={
            "items": [{"subtitle_id": "S0001", "chinese": "我们详谈了他们迂回建造的方式"}]
        },
    ):
        repaired = editor._compress_fast_chinese_segments(
            [segment],
            semantic_groups=groups,
            subtitle_items=[item],
        )

    assert repaired[0].translated_text == "我们详谈了他们迂回建造的方式。"
    assert not editor._is_severe_chinese_speed(repaired[0])


def _words(text):
    return ScreenSubtitleEditor._word_tokens(text)


def _id_editor():
    editor = _editor()
    editor.model = "test-model"
    editor.timeout = 5
    editor.batch_num = 24
    editor.allocation_batch_size = 24
    editor.allocation_max_concurrency = 1
    editor.cache_manager = _NoCache()
    editor.client = None
    editor.max_cjk_chars = 18
    editor._translation_structure_errors = []
    editor._last_llm_raw_returns = []
    editor._last_semantic_group_debug = []
    editor._last_semantic_group_audit_contexts = {}
    editor._last_semantic_group_id_by_subtitle_id = {}
    editor.article_context_prompt = ""
    editor._frozen_subtitle_ids = []
    editor._llm_cache_used = False
    editor._llm_cache_stats = {}
    editor._llm_request_ledger = []
    editor._llm_request_ledger_lock = threading.Lock()
    editor._display_page_external_request_count = 0
    editor._allocation_runtime_stats = {}
    return editor


def test_screen_editor_uses_16_word_stable_hard_floor():
    with patch.object(ScreenSubtitleEditor, "_init_client", return_value=None):
        editor = ScreenSubtitleEditor(
            model="test-model",
            max_english_words=14,
        )

    assert editor.max_english_words == 16


def test_screen_editor_routes_full_translation_and_allocation_models_by_role():
    with patch.object(ScreenSubtitleEditor, "_init_client", return_value=None):
        editor = ScreenSubtitleEditor(
            model="deepseek-v4-flash",
            full_translation_model="deepseek-v4-pro",
            allocation_review_model="deepseek-v4-flash",
        )
    calls = []

    def create(**kwargs):
        calls.append(kwargs["model"])
        if len(calls) == 1:
            content = {
                "groups": [
                    {
                        "id": 1,
                        "source_english": "A complete thought.",
                        "full_translation": "一个完整的意思。",
                    }
                ]
            }
        else:
            content = {"groups": []}
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))]
        )

    editor.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    editor.cache_manager = _NoCache()

    full = editor._request_semantic_full_translation_chunk(
        "full prompt",
        [{"id": 1, "full_english": "A complete thought."}],
        cache_task="test-full-role",
    )
    allocation, error = editor._request_semantic_translation_allocation_api_only(
        "allocation prompt",
        [{"id": 1}],
        cache_task="test-allocation-role",
        max_attempts=1,
    )

    assert full["groups"][0]["full_translation"] == "一个完整的意思。"
    assert allocation == {"groups": []}
    assert error == ""
    assert calls == ["deepseek-v4-pro", "deepseek-v4-flash"]
    metadata = editor.manifest_metadata()
    assert metadata["allocation_quality_retry_model"] == "deepseek-v4-pro"
    assert metadata["display_page_retry_model"] == "deepseek-v4-pro"
    assert metadata["llm_usage_summary"]["external_attempt_count"] == 2
    assert metadata["llm_usage_summary"]["by_model"]["deepseek-v4-pro"][
        "external_attempt_count"
    ] == 1
    assert metadata["llm_usage_summary"]["by_model"]["deepseek-v4-flash"][
        "external_attempt_count"
    ] == 1
    assert metadata["translation_request_policy"] == {
        "configured_budget": 0,
        "budget_scope": "per_stage",
        "max_attempts_per_request": 3,
        "attempts_used": 2,
        "attempts_by_stage": {"screen_subtitle_edit": 2},
        "remaining_attempts": None,
        "remaining_attempts_by_stage": {},
        "budget_exhausted": False,
    }


def test_screen_editor_disables_sdk_level_retries():
    with patch.dict(
        "os.environ",
        {
            "OPENAI_BASE_URL": "https://api.example.test/v1",
            "OPENAI_API_KEY": "test-key",
        },
    ), patch("app.core.subtitle_processor.screen_editor.OpenAI") as openai_client:
        ScreenSubtitleEditor._init_client()

    openai_client.assert_called_once_with(
        base_url="https://api.example.test/v1",
        api_key="test-key",
        max_retries=0,
    )


def test_translation_request_budget_is_isolated_for_display_page_stage():
    editor = _id_editor()
    editor.translation_request_budget = 1
    editor._translation_request_attempts = 0
    editor._translation_request_attempts_by_scope = {}

    assert editor._claim_translation_attempt(
        "screen_subtitle_semantic_full_translation_v7"
    )
    assert not editor._claim_translation_attempt(
        "screen_subtitle_semantic_translation_allocation_v3"
    )
    assert editor._claim_translation_attempt(
        "screen_subtitle_display_page_translation_v2"
    )
    assert editor._translation_request_attempts == 2
    assert editor._translation_request_attempts_by_scope == {
        "screen_subtitle_edit": 1,
        "display_page_translation": 1,
    }


def test_semantic_cache_identity_uses_only_the_request_owner_model():
    editor = _id_editor()
    editor.full_translation_model = "deepseek-v4-pro"
    editor.allocation_review_model = "deepseek-v4-flash"
    editor.display_page_translation_model = "deepseek-v4-flash"
    editor._assign_global_subtitle_ids(_id_items(2))
    prompt = "role-scoped cache"
    payload = [{"id": 1, "full_english": "English 1. English 2."}]
    full_task = "screen_subtitle_semantic_full_translation_v7"
    allocation_task = "screen_subtitle_semantic_translation_allocation_v3"

    full_key = editor._semantic_chinese_cache_key(prompt, payload, full_task)
    allocation_key = editor._semantic_chinese_cache_key(
        prompt, payload, allocation_task
    )
    pro_retry_key = editor._semantic_chinese_cache_key(
        prompt,
        payload,
        "screen_subtitle_semantic_translation_allocation_fragment_retry_v1",
        request_model="deepseek-v4-pro",
    )
    editor._chinese_cache_contract["model_role_policy_version"] = "changed-policy"
    assert editor._semantic_chinese_cache_key(prompt, payload, full_task) == full_key
    editor._chinese_cache_contract["model_role_policy_version"] = (
        "stable-translation-model-roles-v1"
    )

    editor.allocation_review_model = "deepseek-v4-flash-next"
    editor.display_page_translation_model = "deepseek-v4-flash-next"
    assert editor._semantic_chinese_cache_key(prompt, payload, full_task) == full_key
    assert (
        editor._semantic_chinese_cache_key(prompt, payload, allocation_task)
        != allocation_key
    )
    assert (
        editor._semantic_chinese_cache_key(
            prompt,
            payload,
            "screen_subtitle_semantic_translation_allocation_fragment_retry_v1",
            request_model="deepseek-v4-pro",
        )
        == pro_retry_key
    )

    editor.allocation_review_model = "deepseek-v4-flash"
    editor.display_page_translation_model = "deepseek-v4-flash"
    editor.full_translation_model = "deepseek-v4-pro-next"
    assert editor._semantic_chinese_cache_key(prompt, payload, full_task) != full_key
    assert (
        editor._semantic_chinese_cache_key(prompt, payload, allocation_task)
        == allocation_key
    )


def test_screen_manifest_records_translation_model_roles_and_retry_owners():
    thread = SubtitleThread.__new__(SubtitleThread)
    thread._stage_timings_seconds = {}
    thread._article_run_metadata = {}
    editor = SimpleNamespace(
        manifest_metadata=lambda: {
            "translation_model": "deepseek-v4-pro",
            "full_translation_model": "deepseek-v4-pro",
            "allocation_review_model": "deepseek-v4-flash",
            "display_page_translation_model": "deepseek-v4-flash",
            "allocation_quality_retry_model": "deepseek-v4-pro",
            "display_page_retry_model": "deepseek-v4-pro",
            "model_role_policy_version": "stable-translation-model-roles-v1",
            "prompt_version": "global-subtitle-id-v2",
            "translation_request_policy": {
                "configured_budget": 40,
                "max_attempts_per_request": 3,
                "attempts_used": 5,
                "remaining_attempts": 35,
                "budget_exhausted": False,
            },
        },
        model="deepseek-v4-flash",
        target_language="简体中文",
        max_cjk_chars=24,
        max_english_words=16,
        allocation_batch_size=16,
        allocation_max_concurrency=1,
        enable_chinese_polish=False,
    )

    runtime = thread._screen_manifest_metadata(editor)["run_comparison"][
        "translation_runtime_config"
    ]

    assert runtime["translation_model"] == "deepseek-v4-pro"
    assert runtime["full_translation_model"] == "deepseek-v4-pro"
    assert runtime["allocation_review_model"] == "deepseek-v4-flash"
    assert runtime["display_page_translation_model"] == "deepseek-v4-flash"
    assert runtime["allocation_quality_retry_model"] == "deepseek-v4-pro"
    assert runtime["display_page_retry_model"] == "deepseek-v4-pro"
    assert runtime["model_role_policy_version"] == "stable-translation-model-roles-v1"
    assert runtime["translation_request_policy"]["configured_budget"] == 40
    assert runtime["translation_request_policy"]["attempts_used"] == 5


def test_stable_screen_pipeline_requests_word_timestamps_without_legacy_split():
    assert TaskFactory._needs_word_timestamps_for_subtitle_pipeline(
        need_split=False,
        need_screen_subtitle_edit=True,
        screen_subtitle_stable_mode=True,
    )
    assert TaskFactory._needs_word_timestamps_for_subtitle_pipeline(
        need_split=True,
        need_screen_subtitle_edit=False,
        screen_subtitle_stable_mode=False,
    )
    assert not TaskFactory._needs_word_timestamps_for_subtitle_pipeline(
        need_split=False,
        need_screen_subtitle_edit=True,
        screen_subtitle_stable_mode=False,
    )


def test_stable_screen_mode_skips_legacy_llm_optimization():
    assert not SubtitleThread._should_run_legacy_subtitle_optimization(
        need_optimize=True,
        stable_screen_mode=True,
    )
    assert SubtitleThread._should_run_legacy_subtitle_optimization(
        need_optimize=True,
        stable_screen_mode=False,
    )


def test_stable_screen_mode_rejects_missing_or_unmappable_word_ledger():
    source = ASRData([ASRDataSeg("alpha beta.", 0, 400)])
    unmappable_ledger = ASRData(
        [
            ASRDataSeg("gamma", 0, 180),
            ASRDataSeg("delta", 200, 400),
        ]
    )

    for ledger in (None, unmappable_ledger):
        editor = _editor()
        editor.enable_stable_mode = True
        try:
            editor.edit(source, word_time_asr_data=ledger)
        except RuntimeError as exc:
            assert "完整词级账本" in str(exc)
        else:
            raise AssertionError("stable mode must not fall back to legacy screen editing")


class _NoCache:
    def get_llm_result(self, *args, **kwargs):
        return None

    def set_llm_result(self, *args, **kwargs):
        return None


class _QueueCache:
    def __init__(self, results):
        self.results = list(results)
        self.set_calls = []
        self.set_thread_ids = []

    def get_llm_result(self, *args, **kwargs):
        if self.results:
            return self.results.pop(0)
        return None

    def set_llm_result(self, *args, **kwargs):
        self.set_calls.append((args, kwargs))
        self.set_thread_ids.append(threading.get_ident())


class _KeyedCache:
    def __init__(self, entries):
        self.entries = dict(entries)
        self.get_calls = []

    def get_llm_result(self, *args, **kwargs):
        self.get_calls.append((args, kwargs))
        return self.entries.get(args[0])

    def set_llm_result(self, *args, **kwargs):
        self.entries[args[0]] = args[1]


def _id_items(count, translated=""):
    return [
        ScreenSubtitleItem(
            source_ids=[index],
            original=f"English {index}.",
            translated=translated.format(index=index) if translated else "",
            word_start=index * 2,
            word_end=index * 2 + 1,
        )
        for index in range(1, count + 1)
    ]


def _id_group(group_id, start_index, items):
    return {"id": group_id, "start_index": start_index, "items": items}


def test_stable_chinese_cache_rejects_stale_frozen_boundary_context():
    editor = _id_editor()
    before = editor._assign_global_subtitle_ids(
        [
            ScreenSubtitleItem([1], "The system learns from", "", 0, 3),
            ScreenSubtitleItem([2], "feedback over time.", "", 4, 6),
        ]
    )
    payload = [
        {
            "id": 1,
            "full_english": "The system learns from feedback over time.",
            "full_translation": "系统会在长期反馈中学习。",
            "subtitle_parts": [
                {"subtitle_id": "S0001", "english": before[0].original},
                {"subtitle_id": "S0002", "english": before[1].original},
            ],
        }
    ]
    prompt = "fixed-id allocation"
    cache_task = "screen_subtitle_semantic_translation_allocation_v3"
    before_contract = dict(editor._chinese_cache_contract)
    old_key = editor._semantic_chinese_cache_key(prompt, payload, cache_task)
    editor.cache_manager = _KeyedCache(
        {
            old_key: json.dumps(
                {
                    "groups": [
                        {
                            "id": 1,
                            "part_translations": [
                                {"subtitle_id": "S0001", "zh": "旧缓存。"},
                                {"subtitle_id": "S0002", "zh": "旧缓存。"},
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        }
    )

    after = editor._assign_global_subtitle_ids(
        [
            ScreenSubtitleItem([1], "The system learns from feedback", "", 0, 4),
            ScreenSubtitleItem([2], "over time.", "", 5, 6),
        ]
    )
    after_contract = dict(editor._chinese_cache_contract)
    expected_groups = {1: _id_group(1, 0, after)}

    assert before_contract["full_english_text_hash"] == after_contract["full_english_text_hash"]
    assert before_contract["frozen_id_word_span_hash"] != after_contract["frozen_id_word_span_hash"]
    after_payload = [
        {
            **payload[0],
            "subtitle_parts": [
                {"subtitle_id": "S0001", "english": after[0].original},
                {"subtitle_id": "S0002", "english": after[1].original},
            ],
        }
    ]
    # Allocation owns frozen subtitle spans.  A span move must invalidate even
    # when the aggregate English happens to be unchanged.
    assert old_key != editor._semantic_chinese_cache_key(prompt, payload, cache_task)
    assert old_key != editor._semantic_chinese_cache_key(prompt, after_payload, cache_task)
    assert editor._load_cached_allocation_batch(
        prompt,
        payload,
        expected_groups,
        batch_id=1,
        cache_task=cache_task,
    ) is None
    assert editor.cache_manager.get_calls == []


def test_semantic_full_translation_rejects_duplicate_request_group_ids():
    payload = [
        {"id": 1, "full_english": "One.", "source_echo_required": True},
        {"id": 1, "full_english": "One.", "source_echo_required": True},
    ]
    errors = ScreenSubtitleEditor._semantic_full_translation_response_errors(
        {"groups": [{"id": 1, "source_english": "One.", "full_translation": "一。"}]},
        payload,
    )
    assert any(error["code"] == "translation_request_group_id_duplicate" for error in errors)


def test_allocation_payload_rejects_duplicate_group_ids():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids([ScreenSubtitleItem([1], "One.", "", 0, 0)])
    group = _id_group(1, 0, items)
    payload = [
        {"id": 1, "subtitle_parts": [{"subtitle_id": "S0001", "english": "One."}]},
        {"id": 1, "subtitle_parts": [{"subtitle_id": "S0001", "english": "One."}]},
    ]
    assert not editor._allocation_payload_matches_expected_groups(payload, {1: group})


def test_translation_api_only_retries_only_rate_limit_and_respects_budget():
    class RateLimited(Exception):
        status_code = 429

    class Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RateLimited("429")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"groups": []}'))]
            )

    editor = _editor()
    editor.full_translation_model = "flash"
    editor.timeout = 1
    editor.translation_request_max_attempts = 3
    editor.translation_request_budget = 2
    editor._translation_request_attempts = 0
    editor.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    with patch.object(ScreenSubtitleEditor, "_translation_retry_delay_seconds", return_value=0):
        data, error, attempts = editor._request_semantic_full_translation_api_only(
            "prompt", [], cache_task="test-budget"
        )
    assert data == {"groups": []}
    assert error == ""
    assert len(attempts) == 2
    assert editor._translation_request_attempts == 2


def test_full_translation_chunk_records_failed_external_attempt_once():
    class ServiceUnavailable(Exception):
        status_code = 503

    editor = _id_editor()
    editor.cache_manager = _NoCache()
    editor.translation_request_max_attempts = 3
    editor.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: (_ for _ in ()).throw(
                    ServiceUnavailable("Error code: 503")
                )
            )
        )
    )

    result = editor._request_semantic_full_translation_chunk(
        "prompt",
        [{"id": 1, "full_english": "One."}],
        cache_task="test-full-translation-ledger",
        max_attempts=1,
    )

    assert result is None
    assert len(editor._llm_request_ledger) == 1
    assert editor._llm_request_ledger[0]["external_attempt"] is True
    assert editor._llm_request_ledger[0]["status"] == "error"
    assert editor._llm_request_ledger[0]["error_type"] == "ServiceUnavailable"


def test_display_page_api_only_returns_attempts_without_worker_state_writes():
    class RateLimited(Exception):
        status_code = 429

    contract = build_display_page_contract(
        [
            {
                "parent_subtitle_id": "S0001",
                "english": "Alpha beta gamma delta.",
                "chinese": "甲乙丙丁。",
                "word_start": 0,
                "word_end": 3,
                "pages": [
                    {
                        "display_page_id": "S0001.P01",
                        "word_start": 0,
                        "word_end": 1,
                        "english": "Alpha beta",
                        "start_ms": 0,
                        "end_ms": 800,
                    },
                    {
                        "display_page_id": "S0001.P02",
                        "word_start": 2,
                        "word_end": 3,
                        "english": "gamma delta.",
                        "start_ms": 800,
                        "end_ms": 1600,
                    },
                ],
            }
        ],
        layout_profile={"chinese_font_size": 48, "max_lines": 2},
    )

    class Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RateLimited("429")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "pages": [
                                        {
                                            "display_page_id": "S0001.P01",
                                            "source_english": "Alpha beta",
                                            "zh": "甲乙",
                                        },
                                        {
                                            "display_page_id": "S0001.P02",
                                            "source_english": "gamma delta.",
                                            "zh": "丙丁。",
                                        },
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        )
                    )
                ]
            )

    editor = _id_editor()
    editor.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    editor.translation_request_budget = 2
    editor.translation_request_max_attempts = 3
    editor._translation_request_attempts = 0
    with patch.object(ScreenSubtitleEditor, "_translation_retry_delay_seconds", return_value=0):
        data, error, attempts = editor._request_display_page_translation_api_only(
            contract
        )

    assert error == ""
    assert data["pages"][0]["display_page_id"] == "S0001.P01"
    assert len(attempts) == 2
    assert editor._llm_request_ledger == []
    assert editor._display_page_external_request_count == 0


def test_semantic_full_translation_cache_survives_allocation_algorithm_change():
    editor = _id_editor()
    editor._assign_global_subtitle_ids(_id_items(2))
    prompt = "semantic full translation"
    payload = [{"id": 1, "full_english": "English 1. English 2."}]
    full_task = "screen_subtitle_semantic_full_translation_v7"
    allocation_task = "screen_subtitle_semantic_translation_allocation_v3"

    full_key_before = editor._semantic_chinese_cache_key(prompt, payload, full_task)
    allocation_key_before = editor._semantic_chinese_cache_key(prompt, payload, allocation_task)
    editor._chinese_cache_contract["fixed_id_allocation_algorithm_version"] = "changed"
    editor._chinese_cache_contract["semantic_allocation_prompt_version"] = "changed"

    assert editor._semantic_chinese_cache_key(prompt, payload, full_task) == full_key_before
    assert editor._semantic_chinese_cache_key(prompt, payload, allocation_task) != allocation_key_before


def test_semantic_full_translation_reads_verified_legacy_role_cache_once():
    editor = _id_editor()
    editor._assign_global_subtitle_ids(_id_items(2))
    prompt = "semantic full translation"
    payload = [{"id": 1, "full_english": "English 1. English 2."}]
    cache_task = "screen_subtitle_semantic_full_translation_v7"
    current_key = editor._semantic_chinese_cache_key(prompt, payload, cache_task)
    legacy_keys = editor._legacy_semantic_full_translation_cache_keys(
        prompt,
        payload,
        cache_task,
    )
    cached = {"groups": [{"id": 1, "translation": "完整中文。"}]}
    editor.cache_manager = _KeyedCache({legacy_keys[0]: json.dumps(cached, ensure_ascii=False)})

    result = editor._request_semantic_full_translation_chunk(
        prompt,
        payload,
        cache_task=cache_task,
    )

    assert result == cached
    assert editor.cache_manager.entries[current_key] == json.dumps(cached, ensure_ascii=False)


def test_invalid_full_translation_cache_is_replaced_only_by_valid_response():
    payload = [
        {"id": 1, "full_english": "First."},
        {"id": 2, "full_english": "Second."},
    ]
    invalid_cached = {
        "groups": [
            {"id": 1, "full_translation": "第一。"},
            {"id": 1, "full_translation": "重复第一。"},
        ]
    }
    valid_fresh = {
        "groups": [
            {"id": 1, "full_translation": "第一。"},
            {"id": 2, "full_translation": "第二。"},
        ]
    }

    class Cache:
        def __init__(self):
            self.writes = []

        def get_llm_result(self, *args, **kwargs):
            return json.dumps(invalid_cached, ensure_ascii=False)

        def set_llm_result(self, *args, **kwargs):
            self.writes.append(json.loads(args[1]))

    editor = _editor()
    editor.model = "test-model"
    editor.timeout = 5
    editor.cache_manager = Cache()
    editor._llm_cache_stats = {}
    editor._llm_cache_used = False
    editor.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps(valid_fresh, ensure_ascii=False)
                            )
                        )
                    ]
                )
            )
        )
    )

    result = editor._request_semantic_full_translation_chunk(
        "translate",
        payload,
        cache_task="test-full-translation",
    )

    assert result == valid_fresh
    assert editor.cache_manager.writes == [valid_fresh]
    assert editor._llm_cache_stats["test-full-translation"] == {"hit": 0, "miss": 1}


def test_partial_full_translation_cache_preserves_valid_groups_for_resume():
    editor = _id_editor()
    payload = [
        {
            "id": 1,
            "full_english": "First.",
            "source_echo_required": True,
        },
        {
            "id": 2,
            "full_english": "Second.",
            "source_echo_required": True,
        },
    ]
    partial = {
        "groups": [
            {
                "id": 1,
                "source_english": "First.",
                "full_translation": "第一。",
            }
        ]
    }
    task = "test-full-translation-partial"
    key = editor._semantic_chinese_cache_key("translate", payload, task)
    editor.cache_manager = _KeyedCache(
        {key: json.dumps(partial, ensure_ascii=False)}
    )
    editor.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: (_ for _ in ()).throw(
                    AssertionError("recoverable partial cache must not be requested again")
                )
            )
        )
    )

    result = editor._request_semantic_full_translation_chunk(
        "translate",
        payload,
        cache_task=task,
    )

    assert editor._semantic_full_translations_from_response(
        result,
        payload=payload,
    ) == {1: "第一。"}
    assert editor._llm_cache_stats[task] == {"hit": 1, "miss": 0}


def test_full_translation_unit_cache_invalidates_only_context_dependents():
    shared_cache = _KeyedCache({})
    api_calls = []

    def make_editor(texts):
        editor = _id_editor()
        editor.allocation_batch_size = 8
        editor.cache_manager = shared_cache

        def create(**kwargs):
            request_payload = json.loads(kwargs["messages"][1]["content"])
            api_calls.append(tuple(int(entry["id"]) for entry in request_payload))
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "groups": [
                                        {
                                            "id": int(entry["id"]),
                                            "source_english": entry["full_english"],
                                            "full_translation": f"译文-{entry['id']}",
                                        }
                                        for entry in request_payload
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        )
                    )
                ]
            )

        editor.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        items = editor._assign_global_subtitle_ids(
            [
                ScreenSubtitleItem([index], text, "", index * 2, index * 2 + 1)
                for index, text in enumerate(texts, 1)
            ]
        )
        groups = [
            _id_group(index, index - 1, [item])
            for index, item in enumerate(items, 1)
        ]
        return editor, groups

    first, first_groups = make_editor(["One.", "Two.", "Three.", "Four."])
    assert set(first._translate_semantic_group_full_translations(first_groups)) == {1, 2, 3, 4}
    assert api_calls == [(1, 2, 3, 4)]

    second, second_groups = make_editor(
        ["One.", "Two.", "Three.", "Four changed."]
    )
    assert set(second._translate_semantic_group_full_translations(second_groups)) == {1, 2, 3, 4}
    # Radius=2 means G1 has no dependency on G4, while G2/G3 read G4 as a
    # neighbor and G4 itself changed.  This is local invalidation, not an
    # unsafe whole-episode cache reuse.
    assert api_calls[-1] == (2, 3, 4)


def test_full_translation_concurrency_merges_out_of_order_batches_by_id():
    editor = _id_editor()
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    editor.cache_manager = _KeyedCache({})
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [_id_group(index, index - 1, [item]) for index, item in enumerate(items, 1)]
    completions = []

    def request_api(_prompt, payload, *, cache_task, **_kwargs):
        ids = [int(entry["id"]) for entry in payload]
        if ids == [1, 2]:
            time.sleep(0.03)
        completions.append(ids)
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "source_english": entry["full_english"],
                        "full_translation": f"译文-{entry['id']}",
                    }
                    for entry in reversed(payload)
                ]
            },
            "",
            [],
        )

    with patch.object(editor, "_request_semantic_full_translation_api_only", side_effect=request_api):
        result = editor._translate_semantic_group_full_translations(groups)

    assert completions[0] == [3, 4]
    assert sorted(result) == [1, 2, 3, 4], (result, completions)
    assert result == {index: f"译文-{index}" for index in range(1, 5)}


def test_full_translation_scheduler_stops_after_consecutive_provider_failures():
    class ServiceUnavailable(Exception):
        status_code = 503

    editor = _id_editor()
    editor.allocation_batch_size = 16
    editor.allocation_max_concurrency = 2
    editor.cache_manager = _KeyedCache({})
    items = editor._assign_global_subtitle_ids(_id_items(32))
    groups = [
        _id_group(index, index - 1, [item])
        for index, item in enumerate(items, 1)
    ]
    started_batches = []
    stored_group_ids = []
    progress_events = []
    editor.progress_callback = progress_events.append
    initial_workers_started = threading.Barrier(2)
    third_batch_started = threading.Event()

    def request_api(_prompt, payload, *, cache_task, **_kwargs):
        ids = [int(entry["id"]) for entry in payload]
        started_batches.append(ids)
        if ids in (list(range(1, 9)), list(range(9, 17))):
            initial_workers_started.wait(timeout=1)
        if ids == list(range(1, 9)):
            error = ServiceUnavailable("Error code: 503")
            return None, str(error), [{"attempt": 1, "elapsed_seconds": 0.01, "error": error}]
        if ids == list(range(9, 17)):
            assert third_batch_started.wait(timeout=1)
            error = TimeoutError("Request timed out.")
            return None, str(error), [{"attempt": 1, "elapsed_seconds": 0.03, "error": error}]
        if ids == list(range(17, 25)):
            third_batch_started.set()
            time.sleep(0.08)
            return (
                {
                    "groups": [
                        {
                            "id": entry["id"],
                            "source_english": entry["full_english"],
                            "full_translation": f"译文-{entry['id']}",
                        }
                        for entry in payload
                    ]
                },
                "",
                [{"attempt": 1, "elapsed_seconds": 0.08, "response": None}],
            )
        raise AssertionError(f"circuit breaker admitted an extra batch: {ids}")

    original_store = editor._store_semantic_full_translation_units

    def store_units(payload_by_id, translations):
        stored_group_ids.append(sorted(translations))
        return original_store(payload_by_id, translations)

    with patch.object(
        editor,
        "_request_semantic_full_translation_api_only",
        side_effect=request_api,
    ), patch.object(
        editor,
        "_store_semantic_full_translation_units",
        side_effect=store_units,
    ):
        try:
            editor._translate_semantic_group_full_translations(groups)
        except RuntimeError as exc:
            assert str(exc).startswith("semantic_full_translation_provider_unavailable:")
        else:
            raise AssertionError("consecutive provider failures must stop full translation")

    assert {tuple(batch) for batch in started_batches[:2]} == {
        tuple(range(1, 9)),
        tuple(range(9, 17)),
    }
    assert started_batches[-1] == list(range(17, 25))
    assert list(range(25, 33)) not in started_batches
    assert list(range(17, 25)) in stored_group_ids
    assert not any(
        record["task"].endswith("_retry") for record in editor._llm_request_ledger
    )
    assert any(
        event.get("phase") == "full_translation"
        and event.get("failed_batches") == 2
        and event.get("circuit_open") is True
        for event in progress_events
    )


def test_full_translation_scheduler_continues_after_one_provider_failure():
    class ServiceUnavailable(Exception):
        status_code = 503

    editor = _id_editor()
    editor.allocation_batch_size = 16
    editor.allocation_max_concurrency = 2
    editor.cache_manager = _KeyedCache({})
    items = editor._assign_global_subtitle_ids(_id_items(24))
    groups = [
        _id_group(index, index - 1, [item])
        for index, item in enumerate(items, 1)
    ]
    started_batches = []
    initial_workers_started = threading.Barrier(2)

    def response(payload):
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "source_english": entry["full_english"],
                    "full_translation": f"译文-{entry['id']}",
                }
                for entry in payload
            ]
        }

    def request_api(_prompt, payload, *, cache_task, **_kwargs):
        ids = [int(entry["id"]) for entry in payload]
        started_batches.append(ids)
        if ids in (list(range(1, 9)), list(range(9, 17))):
            initial_workers_started.wait(timeout=1)
        if ids == list(range(1, 9)):
            error = ServiceUnavailable("Error code: 503")
            return None, str(error), [{"attempt": 1, "elapsed_seconds": 0.01, "error": error}]
        if ids == list(range(9, 17)):
            time.sleep(0.02)
        return response(payload), "", [{"attempt": 1, "elapsed_seconds": 0.02, "response": None}]

    def repair_missing(*, payload_by_id, result, **_kwargs):
        missing_ids = [group_id for group_id in payload_by_id if group_id not in result]
        result.update({group_id: f"译文-{group_id}" for group_id in missing_ids})
        return 1

    with patch.object(
        editor,
        "_request_semantic_full_translation_api_only",
        side_effect=request_api,
    ), patch.object(
        editor,
        "_retry_missing_semantic_full_translations",
        side_effect=repair_missing,
    ):
        result = editor._translate_semantic_group_full_translations(groups)

    assert sorted(started_batches) == [
        list(range(1, 9)),
        list(range(9, 17)),
        list(range(17, 25)),
    ]
    assert result == {index: f"译文-{index}" for index in range(1, 25)}


def test_display_page_concurrency_caches_completed_batches_immediately():
    parents = []
    for index in range(1, 8):
        parent_id = f"S{index:04d}"
        english = f"alpha {index} beta {index}"
        parents.append(
            {
                "parent_subtitle_id": parent_id,
                "english": english,
                "chinese": f"第{index}条完整中文。",
                "word_start": index * 4,
                "word_end": index * 4 + 3,
                "pages": [
                    {
                        "display_page_id": f"{parent_id}.P01",
                        "word_start": index * 4,
                        "word_end": index * 4 + 1,
                        "english": f"alpha {index}",
                        "start_ms": index * 1000,
                        "end_ms": index * 1000 + 400,
                    },
                    {
                        "display_page_id": f"{parent_id}.P02",
                        "word_start": index * 4 + 2,
                        "word_end": index * 4 + 3,
                        "english": f"beta {index}",
                        "start_ms": index * 1000 + 400,
                        "end_ms": index * 1000 + 900,
                    },
                ],
            }
        )
    contract = build_display_page_contract(
        parents, layout_profile={"chinese_font_size": 48, "max_lines": 2}
    )

    class Cache:
        def __init__(self):
            self.values = {}
            self.write_batches = []

        def get_llm_result(self, key, *_args, **_kwargs):
            return self.values.get(key)

        def set_llm_result(self, key, value, *_args, **_kwargs):
            self.values[key] = value
            self.write_batches.append(
                [row["display_page_id"] for row in json.loads(value)["pages"]]
            )

    cache = Cache()
    editor = _id_editor()
    editor.full_translation_model = "flash"
    editor.allocation_review_model = "flash"
    editor.display_page_translation_model = "flash"
    editor.target_language = "简体中文"
    editor.article_context_prompt = ""
    editor.article_context_data = {}
    editor.allocation_max_concurrency = 2
    editor._display_page_external_request_count = 0
    editor._display_page_translation_reviews = []
    editor.cache_manager = cache
    progress_events = []
    editor.progress_callback = progress_events.append
    calls = []

    def create(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        parent_ids = [parent["parent_subtitle_id"] for parent in payload]
        if len(parent_ids) > 1:
            time.sleep(0.03)
        calls.append(parent_ids)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"pages": [
                {
                    "display_page_id": page["display_page_id"],
                    "source_english": page["english"],
                    "zh": (
                        f"第{int(parent['parent_subtitle_id'][1:])}条"
                        if page["display_page_id"].endswith(".P01")
                        else "完整中文。"
                    ),
                }
                for parent in payload for page in parent["pages"]
            ]}, ensure_ascii=False)))]
        )

    editor.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response, cache_hit = editor._request_display_page_translations(contract)

    assert cache_hit is False
    assert calls[0] == ["S0007"]
    assert cache.write_batches == [
        ["S0007.P01", "S0007.P02"],
        [
            f"S{index:04d}.P{page_index:02d}"
            for index in range(1, 7)
            for page_index in (1, 2)
        ],
    ]
    assert any(
        event.get("phase") == "display_page_translation"
        and event.get("completed") == 1
        and event.get("total") == 2
        for event in progress_events
    )
    assert progress_events[-1]["completed"] == 2
    assert [row["display_page_id"] for row in response["pages"]] == [
        f"S{index:04d}.P{page_index:02d}"
        for index in range(1, 8)
        for page_index in (1, 2)
    ]


def test_final_allocation_unit_cache_resumes_without_batch_request():
    shared_cache = _KeyedCache({})

    def make_editor_and_payload():
        editor = _id_editor()
        editor.cache_manager = shared_cache
        items = editor._assign_global_subtitle_ids(
            [
                ScreenSubtitleItem([1], "Alice arrived.", "", 0, 1),
                ScreenSubtitleItem([2], "Bob left.", "", 2, 3),
            ]
        )
        group = _id_group(1, 0, items)
        payload = [
            {
                "id": 1,
                "full_english": "Alice arrived. Bob left.",
                "full_translation": "爱丽丝到了。鲍勃离开了。",
                "subtitle_parts": [
                    {"subtitle_id": "S0001", "english": "Alice arrived."},
                    {"subtitle_id": "S0002", "english": "Bob left."},
                ],
            }
        ]
        return editor, payload, {1: group}

    first, payload, expected = make_editor_and_payload()
    allocation = {1: {"S0001": "爱丽丝到了。", "S0002": "鲍勃离开了。"}}
    first._store_allocation_units(payload, expected, allocation)

    second, resumed_payload, resumed_expected = make_editor_and_payload()
    assert second._load_cached_allocation_units(
        resumed_payload,
        resumed_expected,
    ) == allocation


def test_llm_request_ledger_persists_token_and_reasoning_usage():
    editor = _id_editor()
    editor._llm_request_ledger = []
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "episode-coverage-report.txt"
        editor.coverage_report_path = str(report_path)
        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=30,
                total_tokens=150,
                prompt_cache_hit_tokens=80,
                prompt_cache_miss_tokens=40,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=9),
            )
        )

        editor._record_llm_request(
            task="screen_subtitle_semantic_full_translation_v7",
            model="deepseek-v4-pro",
            cache_hit=False,
            elapsed_seconds=1.25,
            response=response,
            attempt=1,
            payload_count=8,
        )

        ledger_path = Path(temp_dir) / "episode-artifacts" / "llm-request-ledger.json"
        persisted = json.loads(ledger_path.read_text(encoding="utf-8"))

    assert persisted[0]["usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
        "prompt_cache_hit_tokens": 80,
        "prompt_cache_miss_tokens": 40,
        "reasoning_tokens": 9,
    }
    assert editor._llm_usage_summary() == {
        "request_count": 1,
        "external_attempt_count": 1,
        "successful_external_request_count": 1,
        "failed_external_request_count": 0,
        "cache_hit_count": 0,
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "reasoning_tokens": 9,
        "total_tokens": 150,
        "prompt_cache_hit_tokens": 80,
        "prompt_cache_miss_tokens": 40,
        "by_model": {
            "deepseek-v4-pro": {
                "external_attempt_count": 1,
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "reasoning_tokens": 9,
                "total_tokens": 150,
            }
        },
        "by_task": {
            "screen_subtitle_semantic_full_translation_v7": {
                "external_attempt_count": 1,
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "reasoning_tokens": 9,
                "total_tokens": 150,
            }
        },
    }


def test_invalid_allocation_cache_is_replaced_only_after_id_validation():
    entry = {
        "id": 1,
        "full_english": "Hello world.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Hello world."}
        ],
    }
    payload = [entry]
    expected_group = {
        "id": 1,
        "start_index": 0,
        "items": [
            ScreenSubtitleItem(
                source_ids=[1],
                original="Hello world.",
                translated="",
                subtitle_id="S0001",
            )
        ],
    }
    groups_by_id = {1: expected_group}
    invalid_cached = {
        "groups": [
            {
                "id": 1,
                "part_translations": [
                    {"subtitle_id": "S9999", "zh": "错误缓存"}
                ],
            }
        ]
    }
    valid_fresh = {
        "groups": [
            {
                "id": 1,
                "part_translations": [
                    {"subtitle_id": "S0001", "zh": "你好，世界。"}
                ],
            }
        ]
    }

    class Cache:
        def __init__(self):
            self.writes = []

        def get_llm_result(self, *args, **kwargs):
            return json.dumps(invalid_cached, ensure_ascii=False)

        def set_llm_result(self, *args, **kwargs):
            self.writes.append(json.loads(args[1]))

    editor = _editor()
    editor.model = "test-model"
    editor.timeout = 5
    editor.cache_manager = Cache()
    editor._llm_cache_stats = {}
    editor._llm_cache_used = False
    editor.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps(valid_fresh, ensure_ascii=False)
                            )
                        )
                    ]
                )
            )
        )
    )

    result = editor._request_semantic_translation_allocation(
        "allocate",
        payload,
        cache_task="test-allocation",
        expected_groups_by_id=groups_by_id,
    )

    parsed, complete, errors, _ = editor._parse_allocation_chunk_data_isolated(
        payload,
        groups_by_id,
        result,
    )
    assert complete is True
    assert errors == []
    assert parsed == {1: {"S0001": "你好，世界。"}}
    assert editor.cache_manager.writes == [valid_fresh]
    assert editor._llm_cache_stats["test-allocation"] == {"hit": 0, "miss": 1}


def _codes(editor):
    return {issue["code"] for issue in editor._translation_structure_errors}


def _semantic_context(group_id, subtitle_ids, full_english, full_translation):
    return {
        "semantic_group_id": f"G{group_id:04d}",
        "group_id": group_id,
        "full_english": full_english,
        "full_english_signature": ScreenSubtitleEditor._semantic_audit_signature(full_english),
        "expected_subtitle_ids": list(subtitle_ids),
        "full_translation": full_translation,
        "mapping_valid": True,
    }


def _id_segments(count, translated="这是原文"):
    segments = []
    for index in range(1, count + 1):
        segment = ASRDataSeg(
            f"English {index}.",
            (index - 1) * 1000,
            index * 1000,
            translated,
        )
        segment.subtitle_id = f"S{index:04d}"
        segments.append(segment)
    return segments


def _marker_editor(words, max_words=14):
    editor = _id_editor()
    editor.max_english_words = max_words
    editor._active_word_entries = [
        {
            "token": ScreenSubtitleEditor._word_tokens(word)[0],
            "surface": word,
            "start_time": index * 200,
            "end_time": index * 200 + 120,
        }
        for index, word in enumerate(words)
    ]
    editor._active_source_word_spans = {
        index + 1: (index, index)
        for index in range(len(words))
    }
    editor._active_source_segments_by_id = {
        index + 1: ASRDataSeg(word, index * 200, index * 200 + 120, "")
        for index, word in enumerate(words)
    }
    editor._discourse_marker_orphans = []
    return editor


def _word_item(editor, start, end, source_id=None):
    return ScreenSubtitleItem(
        source_ids=[source_id if source_id is not None else start + 1],
        original=editor._text_from_word_span(start, end),
        translated="",
        word_start=start,
        word_end=end,
    )


class _StaticCache:
    def __init__(self, value):
        self.value = value

    def get_llm_result(self, *args, **kwargs):
        return json.dumps(self.value, ensure_ascii=False)

    def set_llm_result(self, *args, **kwargs):
        raise AssertionError("cache-backed test must not write")


def _assert_stable_split(text, max_words=16, *, allow_complete_overflow=False):
    parts = _split_text(text, max_words=max_words)
    assert parts
    rebuilt = [word for part in parts for word in _words(part)]
    assert rebuilt == _words(text)
    for part in parts:
        if len(_words(part)) > max_words:
            assert allow_complete_overflow, part
            assert len(parts) == 1, parts
            assert part.rstrip().endswith((".", "?", "!")), part
        first = _words(part)[0]
        last = _words(part)[-1]
        assert first not in {"of", "for", "with", "by", "to"}, parts
        assert last not in {"a", "an", "the", "to", "of", "for", "with", "by"}, parts


def test_preposition_phrase_is_not_stranded():
    _assert_stable_split(
        "If the market starts seeing the Fed as just a piggy bank to seamlessly fund government deficits, they lose credibility.",
        allow_complete_overflow=True,
    )


def test_number_and_policy_sentence_keeps_readable_boundaries():
    _assert_stable_split(
        "From 1980 to 2015, the cultural preference for sons in a deeply patriarchal society led to decades of aborted female fetuses."
    )


def test_long_finance_sentence_keeps_full_coverage():
    _assert_stable_split(
        "Although the central bank can reduce its footprint, it cannot drain these massive financial reservoirs without triggering a drought.",
        allow_complete_overflow=True,
    )


def test_missing_translation_is_reported_but_not_blocking():
    editor = _editor()
    source = [ASRDataSeg("Hello world.", 0, 1000)]
    final = [ASRDataSeg("Hello world.", 0, 1000, translated_text="")]

    editor._report_subtitle_coverage_gaps(source, final)

    assert editor.last_validation_summary["status"] == "ERROR"
    assert not editor.has_blocking_validation_errors()
    assert editor.blocking_validation_message() == ""


def test_suspicious_cut_is_warning_not_blocking():
    editor = _editor()
    source = [
        ASRDataSeg("Like, why risk that?", 0, 1200, translated_text="为什么要冒这个险？"),
        ASRDataSeg("Well,", 1240, 1600, translated_text="嗯，"),
    ]

    editor._report_subtitle_coverage_gaps(source, source)

    assert editor.last_validation_summary["status"] == "WARNING"
    assert not editor.has_blocking_validation_errors()


def test_abnormal_timing_gap_is_repaired_for_compressed_cluster():
    editor = _editor()
    segments = [
        ASRDataSeg("and, you know, wants to drain it.", 20580, 22740, "并且想要把它抽干。"),
        ASRDataSeg(
            "Which sounds kind of crazy if the town is literally surviving on that water.",
            27960,
            28700,
            "如果这个城镇确实是靠这水生存的，听起来就有点疯狂了。",
        ),
        ASRDataSeg("Like, why take the risk?", 28700, 29200, "为什么要冒这个风险？"),
        ASRDataSeg(
            "Right. And that is the exact dilemma facing the new Fed chairman right now.",
            29200,
            31280,
            "这正是新任美联储主席目前面临的困境。",
        ),
        ASRDataSeg(
            "So today, we're taking a deep dive into the Federal Reserve's massive balance sheet.",
            32140,
            36640,
            "今天我们深入探讨美联储庞大的资产负债表。",
        ),
    ]

    repaired = editor._repair_abnormal_timing_gaps(segments)

    assert repaired[1].start_time < 24000
    assert repaired[1].start_time - repaired[0].end_time <= 100
    assert repaired[3].end_time <= segments[4].start_time


def test_coverage_gap_does_not_sum_natural_pauses():
    editor = _editor()
    source = [
        ASRDataSeg(
            "But here's where it gets really interesting. Because the sources show the other massive drop in our albedo is directly tied to, well, less pollution.",
            122640,
            132600,
        )
    ]
    final = [
        ASRDataSeg("But here's where it gets really interesting.", 122640, 123960, "ok"),
        ASRDataSeg(
            "Because the sources show the other massive drop in our albedo",
            124980,
            128880,
            "ok",
        ),
        ASRDataSeg("is directly tied to, well, less pollution.", 129360, 132600, "ok"),
    ]

    editor._report_subtitle_coverage_gaps(source, final)

    assert editor.last_validation_summary["status"] != "ERROR"
    assert not editor.has_blocking_validation_errors()


def test_coverage_gap_blocks_single_long_uncovered_span():
    editor = _editor()
    source = [ASRDataSeg("This should remain covered by subtitles.", 0, 5000)]
    final = [
        ASRDataSeg("This should", 0, 1000, "ok"),
        ASRDataSeg("remain covered by subtitles.", 2700, 5000, "ok"),
    ]

    editor._report_subtitle_coverage_gaps(source, final)

    assert editor.last_validation_summary["status"] == "WARNING"
    assert not editor.has_blocking_validation_errors()
    assert any(
        issue["code"] == "coverage_gap_unverified"
        for issue in editor.last_validation_summary["warnings"]
    )


def _coverage_segment(text, start, end, subtitle_id, word_start, word_end):
    segment = ASRDataSeg(text, start, end, "中文")
    segment.subtitle_id = subtitle_id
    segment.word_start = word_start
    segment.word_end = word_end
    segment.stable_word_start_ms = word_start
    segment.stable_word_end_ms = word_end
    return segment


def test_final_display_coverage_audit_preserves_timeline_chaining():
    editor = _editor()
    source = [
        ASRDataSeg("Continuous", 0, 1000),
        ASRDataSeg("source speech.", 1100, 3000),
    ]
    segments = [
        _coverage_segment("First subtitle.", 0, 1300, "S0001", 0, 1000),
        _coverage_segment("Second subtitle.", 1300, 3000, "S0002", 1100, 3000),
    ]
    editor._final_cue_timeline = {
        "boundary_reconciliations": [
            {
                "code": "final_timeline_short_gap_chained",
                "left_subtitle_id": "S0001",
                "right_subtitle_id": "S0002",
                "new_boundary_ms": 1300,
            }
        ]
    }

    repaired = editor._audit_final_display_coverage(segments, source)

    assert repaired[0].end_time == 1300
    assert repaired[1].start_time == 1300
    assert repaired[0].text == segments[0].text
    assert repaired[1].translated_text == segments[1].translated_text
    assert repaired[0].subtitle_id == "S0001"
    assert repaired[1].subtitle_id == "S0002"
    assert repaired[0].stable_word_end_ms == 1000
    assert repaired[1].stable_word_start_ms == 1100
    assert editor._display_coverage_repairs[0]["code"] == "final_timeline_short_gap_chained"
    assert editor._display_coverage_unresolved == []


def test_final_display_coverage_audit_reports_long_gap_without_retiming():
    editor = _editor()
    source = [ASRDataSeg("Continuous source speech.", 0, 4000)]
    segments = [
        _coverage_segment("First subtitle.", 0, 1000, "S0001", 0, 1000),
        _coverage_segment("Second subtitle.", 2200, 4000, "S0002", 1050, 4000),
    ]

    repaired = editor._audit_final_display_coverage(segments, source)

    assert [(item.start_time, item.end_time) for item in repaired] == [(0, 1000), (2200, 4000)]
    assert editor._display_coverage_repairs == []
    assert (
        editor._display_coverage_unresolved[0]["reason"]
        == "gap_remains_after_final_timeline_chaining"
    )


def test_final_display_coverage_audit_reports_real_word_pause_without_retiming():
    editor = _editor()
    source = [ASRDataSeg("Source segment with a pause.", 0, 3000)]
    segments = [
        _coverage_segment("First subtitle.", 0, 1000, "S0001", 0, 1000),
        _coverage_segment("Second subtitle.", 1500, 3000, "S0002", 1600, 3000),
    ]

    repaired = editor._audit_final_display_coverage(segments, source)

    assert [(item.start_time, item.end_time) for item in repaired] == [(0, 1000), (1500, 3000)]
    assert editor._display_coverage_repairs == []
    assert editor._display_coverage_unresolved[0]["reason"] == "frozen_word_pause_exceeds_limit"


def test_final_time_alignment_keeps_final_timeline_chaining():
    editor = _editor()
    source = ASRDataSeg("Continuous source speech.", 0, 3000)
    editor._active_source_segments_by_id = {1: source}
    editor._last_semantic_groups = []
    editor._last_subtitle_items = []
    editor._compress_fast_chinese_segments = lambda segments, **kwargs: list(segments)
    editor._align_segment_translation_punctuation = lambda segments: list(segments)
    editor._report_subtitle_coverage_gaps = lambda *args, **kwargs: None
    editor._write_stable_pipeline_artifacts = lambda **kwargs: None
    asr_data = ASRData(
        [
            _coverage_segment("First subtitle.", 0, 1300, "S0001", 0, 1000),
            _coverage_segment("Second subtitle.", 1300, 3000, "S0002", 1100, 3000),
        ]
    )
    editor._final_cue_timeline = {
        "boundary_reconciliations": [
            {
                "code": "final_timeline_short_gap_chained",
                "left_subtitle_id": "S0001",
                "right_subtitle_id": "S0002",
                "new_boundary_ms": 1300,
            }
        ]
    }

    repaired = editor.repair_after_final_time_alignment(asr_data, preserve_aligned_timing=True)

    assert [(item.start_time, item.end_time) for item in repaired.segments] == [(0, 1300), (1300, 3000)]
    assert [item.subtitle_id for item in repaired.segments] == ["S0001", "S0002"]
    assert editor._display_coverage_repairs[0]["code"] == "final_timeline_short_gap_chained"


def test_chinese_reading_speed_error_is_reported_but_not_blocking():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "This is short.",
            0,
            1500,
            "这条中文字幕明显太长观众基本没有办法在一秒内读完",
        )
    ]

    editor._report_subtitle_coverage_gaps(segments, segments)

    assert editor.last_validation_summary["status"] == "ERROR"
    assert not editor.has_blocking_validation_errors()
    assert any(
        issue["code"] == "reading_speed_error"
        for issue in editor.last_validation_summary["errors"]
    )


def test_near_threshold_chinese_speed_is_a_warning_not_a_render_error():
    editor = _editor()
    segment = ASRDataSeg(
        "They call them job creators.",
        0,
        1241,
        "他们把这些小企业称为就业创造者。",
    )

    health = editor._subtitle_health_issues([segment])

    assert health["reading_speed_errors"] == []
    assert health["reading_speed_warnings"][0]["cps"] == 12.09
    editor._report_subtitle_coverage_gaps([segment], [segment])
    assert editor.last_validation_summary["status"] == "WARNING"
    assert editor.last_validation_summary["errors"] == []


def test_validation_report_adds_actionable_review_tiers_without_changing_status():
    editor = _editor()
    editor._translation_structure_errors = [
        {
            "code": "final_translation_id_mismatch",
            "message": "final id mismatch",
            "missing_subtitle_ids": ["S0002"],
        }
    ]
    health = {
        "overlong_english": [],
        "bad_cuts": [],
        "translationese": [],
        "reading_speed_errors": [
            {
                "subtitle_id": "S0001",
                "chars_per_second": 18.5,
                "text": "too fast",
            }
        ],
        "reading_speed_warnings": [],
        "duration_errors": [],
        "duration_warnings": [],
        "duplicate_chinese": [],
        "asr_suspicious": [],
        "discourse_marker_orphans": [],
        "syntax_boundary_audit": [],
        "chinese_semantic_group_warnings": [],
        "chinese_semantic_group_info": [],
    }

    summary = editor._validation_summary([], [], health, [ASRDataSeg("Hello.", 0, 1000, "Ni hao.")])
    review_items = summary["review"]["items"]

    assert summary["status"] == "ERROR"
    assert any(item["code"] == "final_translation_id_mismatch" for item in summary["errors"])
    assert any(
        item["code"] == "final_translation_id_mismatch"
        and item["severity"] == "BLOCKER"
        and item["affected_subtitle_ids"] == ["S0002"]
        for item in review_items
    )
    assert any(
        item["code"] == "reading_speed_error"
        and item["severity"] == "REVIEW"
        and item["affected_subtitle_ids"] == ["S0001"]
        for item in review_items
    )
    assert any(item["code"] == "subtitle_stats" and item["severity"] == "INFO" for item in review_items)
    assert summary["review"]["summary"]["blocker_count"] >= 1
    assert summary["review"]["summary"]["review_count"] >= 1


def test_validation_review_includes_allocation_unresolved_without_old_error_mutation():
    editor = _editor()
    editor._last_allocation_unresolved = [
        {
            "semantic_group_id": "G0007",
            "reason": "retry_quality_failed",
            "issue_codes": ["number_allocation_mismatch"],
            "allocation": {"S0010": "A", "S0011": "B"},
        }
    ]
    health = {
        "overlong_english": [],
        "bad_cuts": [],
        "translationese": [],
        "reading_speed_errors": [],
        "reading_speed_warnings": [],
        "duration_errors": [],
        "duration_warnings": [],
        "duplicate_chinese": [],
        "asr_suspicious": [],
        "discourse_marker_orphans": [],
        "syntax_boundary_audit": [],
        "chinese_semantic_group_warnings": [],
        "chinese_semantic_group_info": [],
    }

    summary = editor._validation_summary([], [], health, [ASRDataSeg("Hello.", 0, 1000, "Ni hao.")])

    assert summary["errors"] == []
    assert summary["status"] == "PASS"
    assert any(
        item["code"] == "allocation_quality_unresolved"
        and item["severity"] == "BLOCKER"
        and item["semantic_group_ids"] == ["G0007"]
        and item["affected_subtitle_ids"] == ["S0010", "S0011"]
        for item in summary["review"]["items"]
    )


def test_allocation_isolation_report_passes_when_only_chinese_changes():
    editor = _id_editor()
    editor._active_word_entries = [
        {"surface": "Alice", "token": "alice", "start_time": 0, "end_time": 500},
        {"surface": "arrived", "token": "arrived", "start_time": 500, "end_time": 1000},
    ]
    items = editor._assign_global_subtitle_ids(_id_items(1))
    items[0].original = "Alice arrived."
    items[0].translated = "old"
    items[0].word_start = 0
    items[0].word_end = 1
    groups = [_id_group(1, 0, items)]
    full_translations = {1: "Alice arrived."}
    source = [ASRDataSeg("Alice arrived.", 0, 1000)]

    before = editor._allocation_isolation_snapshot(
        stage="before_allocation",
        source_segments=source,
        items=items,
        semantic_groups=groups,
        full_translations=full_translations,
    )
    items[0].translated = "new"
    after = editor._allocation_isolation_snapshot(
        stage="before_export",
        source_segments=source,
        items=items,
        semantic_groups=groups,
        full_translations=full_translations,
        final_segments=[ASRDataSeg("Alice arrived.", 0, 1000, "new")],
    )
    report = editor._build_allocation_isolation_report(before, after)

    assert report["status"] == "passed"
    assert report["changed_keys"] == []


def test_allocation_isolation_report_fails_on_english_boundary_change():
    editor = _id_editor()
    editor._active_word_entries = [
        {"surface": "Alice", "token": "alice", "start_time": 0, "end_time": 500},
        {"surface": "arrived", "token": "arrived", "start_time": 500, "end_time": 1000},
    ]
    items = editor._assign_global_subtitle_ids(_id_items(1))
    items[0].original = "Alice arrived."
    items[0].word_start = 0
    items[0].word_end = 1
    groups = [_id_group(1, 0, items)]
    source = [ASRDataSeg("Alice arrived.", 0, 1000)]
    before = editor._allocation_isolation_snapshot(
        stage="before_allocation",
        source_segments=source,
        items=items,
        semantic_groups=groups,
        full_translations={1: "Alice arrived."},
    )

    changed_items = list(items)
    changed_items[0] = ScreenSubtitleItem(
        source_ids=items[0].source_ids,
        original="Alice arrived today.",
        translated=items[0].translated,
        word_start=items[0].word_start,
        word_end=items[0].word_end,
        subtitle_id=items[0].subtitle_id,
    )
    changed_groups = [_id_group(1, 0, changed_items)]
    after = editor._allocation_isolation_snapshot(
        stage="before_export",
        source_segments=source,
        items=changed_items,
        semantic_groups=changed_groups,
        full_translations={1: "Alice arrived."},
    )
    report = editor._build_allocation_isolation_report(before, after)

    assert report["status"] == "allocation_isolation_failed"
    assert "english_text_hash" in report["changed_keys"]
    assert report["first_differences"]["english_text_hash"]["index"] == 1


def test_duplicate_chinese_is_warning_not_blocking():
    editor = _editor()
    segments = [
        ASRDataSeg("This is one point.", 0, 2500, "这是同一个观点"),
        ASRDataSeg("This is another point.", 2600, 5100, "这是同一个观点"),
    ]

    editor._report_subtitle_coverage_gaps(segments, segments)

    assert editor.last_validation_summary["status"] == "WARNING"
    assert not editor.has_blocking_validation_errors()
    assert any(
        issue["code"] == "duplicate_chinese"
        for issue in editor.last_validation_summary["warnings"]
    )


def test_repeated_english_with_repeated_chinese_is_not_a_duplicate_warning():
    editor = _editor()
    segments = [
        ASRDataSeg("303 billion.", 0, 1200, "3030亿。"),
        ASRDataSeg("303 billion.", 1300, 2500, "3030亿。"),
    ]

    editor._report_subtitle_coverage_gaps(segments, segments)

    duplicate_groups = [
        issue
        for issue in editor.last_validation_summary["warnings"]
        if issue["code"] == "duplicate_chinese"
    ]
    assert duplicate_groups == []


def test_overlong_english_segment_is_locally_split_without_llm():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "Which explains why even graduates with degrees in IT services are struggling right now in many markets today.",
            0,
            4500,
            "这也解释了为什么即使是IT服务专业的毕业生现在也举步维艰。",
        )
    ]

    repaired = editor._repair_overlong_english_segments_local(segments)

    assert len(repaired) == 2
    assert " ".join(seg.text for seg in repaired) == segments[0].text
    assert all(editor._word_count(seg.text) <= 14 for seg in repaired)
    assert repaired[0].start_time == 0
    assert repaired[-1].end_time == 4500


def test_audit_parser_does_not_count_chinese_line_with_it_as_english():
    english, chinese = split_bilingual_body(
        [
            "Which explains why even graduates with degrees in IT services are struggling right now.",
            "这也解释了为什么即使是IT服务专业的毕业生现在也举步维艰。",
        ]
    )

    assert count_words(english) == 14
    assert chinese.startswith("这也解释了")


def test_888_chinese_speed_compression_rejects_dangling_fragment():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "And if we connect this to the bigger picture,",
            358620,
            360260,
            "\u800c\u5982\u679c\u6211\u4eec\u628a\u8fd9\u4e2a\u8bdd\u9898\u8054\u7cfb\u5230\u66f4\u5b8f\u89c2\u7684\u5c42\u9762\uff0c",
        ),
        ASRDataSeg(
            "it raises a huge existential question for the entire corporate world.",
            360260,
            364000,
            "\u5c31\u5f15\u51fa\u4e86\u4e00\u4e2a\u5173\u4e4e\u6574\u4e2a\u4f01\u4e1a\u754c\u7684\u5de8\u5927\u751f\u5b58\u6027\u8d28\u7591\u3002",
        ),
        ASRDataSeg("What question?", 364000, 365200, "\u4ec0\u4e48\u8d28\u7591\uff1f"),
    ]

    assert not editor._is_valid_chinese_compression(
        "\u800c\u82e5\u8054\u7cfb\u66f4\u5b8f\u89c2\u5c42\u9762\uff0c",
        segments[0],
        segments,
        0,
    )
    assert editor._is_valid_chinese_compression(
        "\u518d\u4ece\u5b8f\u89c2\u5c42\u9762\u6765\u770b\uff0c",
        segments[0],
        segments,
        0,
    )


def test_888_chinese_speed_compression_uses_semantic_group_context():
    editor = _editor()
    editor._last_semantic_full_translations = {
        1: "\u518d\u4ece\u5b8f\u89c2\u5c42\u9762\u6765\u770b\uff0c\u6574\u4e2a\u4f01\u4e1a\u754c\u90fd\u9762\u4e34\u4e00\u4e2a\u751f\u6b7b\u6538\u5173\u7684\u95ee\u9898\u3002"
    }
    items = [
        ScreenSubtitleItem([1], "And if we connect this to the bigger picture,", "\u800c\u5982\u679c\u6211\u4eec\u628a\u8fd9\u4e2a\u8bdd\u9898\u8054\u7cfb\u5230\u66f4\u5b8f\u89c2\u7684\u5c42\u9762\uff0c", 0, 8),
        ScreenSubtitleItem([1], "it raises a huge existential question for the entire corporate world.", "\u5c31\u5f15\u51fa\u4e86\u4e00\u4e2a\u5173\u4e4e\u6574\u4e2a\u4f01\u4e1a\u754c\u7684\u5de8\u5927\u751f\u5b58\u6027\u8d28\u7591\u3002", 9, 18),
        ScreenSubtitleItem([1], "What question?", "\u4ec0\u4e48\u8d28\u7591\uff1f", 19, 20),
    ]
    segments = [
        ASRDataSeg(items[0].original, 358620, 360260, items[0].translated),
        ASRDataSeg(items[1].original, 360260, 364000, items[1].translated),
        ASRDataSeg(items[2].original, 364000, 365200, items[2].translated),
    ]
    context = editor._semantic_context_for_segment_index(
        0,
        segments,
        semantic_groups=[{"id": 1, "start_index": 0, "items": items}],
        subtitle_items=items,
    )

    assert context["full_translation"] == "\u518d\u4ece\u5b8f\u89c2\u5c42\u9762\u6765\u770b\uff0c\u6574\u4e2a\u4f01\u4e1a\u754c\u90fd\u9762\u4e34\u4e00\u4e2a\u751f\u6b7b\u6538\u5173\u7684\u95ee\u9898\u3002"
    assert len(context["parts"]) == 3
    assert context["parts"][1]["english"].startswith("it raises")


def test_000_group_validation_rejects_lost_ponder_action():
    editor = _editor()
    editor._last_semantic_full_translations = {
        1: "\u8fd9\u662f\u4e2a\u503c\u5f97\u601d\u8003\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u8def\u8fc7\u7a7a\u7f6e\u653f\u5e9c\u5927\u697c\u65f6\uff0c\u4e0d\u59a8\u60f3\u60f3\u8fd9\u4e2a\u95ee\u9898\u3002"
    }
    items = [
        ScreenSubtitleItem([1], "It's a good question to ponder next time you", "\u8fd9\u662f\u4e00\u4e2a\u5f88\u597d\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u4f60", 0, 8),
        ScreenSubtitleItem([1], "pass an empty government building.", "\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c\u65f6\u53ef\u4ee5\u601d\u8003\u4e00\u4e0b\u3002", 9, 13),
    ]
    segments = [
        ASRDataSeg(items[0].original, 264000, 266420, items[0].translated),
        ASRDataSeg(items[1].original, 266420, 267880, items[1].translated),
    ]
    context = editor._semantic_context_for_segment_index(
        1,
        segments,
        semantic_groups=[{"id": 1, "start_index": 0, "items": items}],
        subtitle_items=items,
    )

    assert not editor._is_valid_group_chinese_allocation(
        {1: "\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c"},
        segments,
        context,
    )
    assert editor._is_valid_group_chinese_allocation(
        {
            0: "\u8fd9\u662f\u4e2a\u503c\u5f97\u601d\u8003\u7684\u95ee\u9898\u3002",
            1: "\u4e0b\u6b21\u8def\u8fc7\u7a7a\u7f6e\u653f\u5e9c\u5927\u697c\u65f6\u60f3\u60f3\u3002",
        },
        segments,
        context,
    )


def test_444_independent_syntax_boundary_audit_catches_bad_cuts():
    editor = _editor()
    bad_boundaries = [
        ("shows we're", "rapidly losing"),
        ("sulfur dioxide into", "the air"),
        ("forces", "a really uncomfortable look"),
        ("hunkering", "down"),
        ("the absolute", "extreme edge"),
        ("Stardust Solutions", "are trying"),
        ("we can alter", "the atmosphere"),
        ("be forced", "to put"),
    ]

    for left, right in bad_boundaries:
        assert editor._syntax_boundary_reasons(left, right), (left, right)


def test_syntax_boundary_audit_ignores_safe_short_dialogue():
    editor = _editor()

    assert not editor._syntax_boundary_reasons("What question?", "Exactly.")
    assert not editor._syntax_boundary_reasons("Right.", "Okay, let's unpack this.")
    assert not _syntax_boundary_reasons("pump water in.", "But the next part matters.")
    assert not _syntax_boundary_reasons("bringing in.", "Wow, that is a lot.")
    assert not _syntax_boundary_reasons("much further than that.", "What do you mean?")


def test_syntax_boundary_audit_keeps_confirmed_bad_cuts():
    confirmed = [
        ("cooling machinery's", "efficiency"),
        ("the Fed's", "massive footprint"),
        ("Rajan's", "rather provocative idea"),
        ("they took", "this low-lying"),
        ("state assets across", "the 10 most active provinces"),
        ("A 56 year-old man is weaving a loaded", "motorized scooter"),
        ("motorized scooter through the dense", "chaotic traffic"),
        ("we really have to look", "at the mechanics"),
    ]

    for left, right in confirmed:
        assert _syntax_boundary_reasons(left, right), (left, right)


def test_chinese_semantic_group_audit_warns_on_lost_core_action():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "That is a very good question to ponder next time you",
            263940,
            266420,
            "\u8fd9\u662f\u4e00\u4e2a\u5f88\u597d\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u4f60",
        ),
        ASRDataSeg(
            "pass an empty government building.",
            266420,
            267880,
            "\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c",
        ),
    ]
    english = " ".join(seg.text for seg in segments)
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(
            1,
            ["S0001", "S0002"],
            english,
            "\u8fd9\u662f\u4e00\u4e2a\u503c\u5f97\u601d\u8003\u7684\u95ee\u9898\uff0c\u4e0b\u6b21\u4f60\u7ecf\u8fc7\u4e00\u680b\u7a7a\u7f6e\u7684\u653f\u5e9c\u5927\u697c\u65f6\u53ef\u4ee5\u601d\u8003\u4e00\u4e0b\u3002",
        )
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0001": "G0001", "S0002": "G0001"}

    issues = editor._chinese_semantic_group_audit_issues(segments)

    assert issues
    assert "semantic_loss" in issues[0]["reason"]


def test_chinese_semantic_audit_skips_semantic_loss_when_mapping_invalid():
    editor = _editor()
    segments = [
        ASRDataSeg("Bouncing the sunlight away.", 1000, 2500, "\u628a\u9633\u5149\u53cd\u5c04\u56de\u53bb\u3002")
    ]
    editor._last_semantic_group_audit_contexts = {
        "G0002": _semantic_context(2, ["S0002"], "Yeah.", "\u662f\u7684\u3002"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0002": "G0002"}

    issues = editor._chinese_semantic_group_audit_issues(segments, "WARNING")

    assert not [issue for issue in issues if "semantic_loss" in issue.get("reason", "")]


def test_chinese_semantic_audit_ignores_normal_short_responses():
    editor = _editor()
    samples = [
        ("Good question.", "问得好。"),
        ("Oh, yeah.", "哦，是的。"),
        ("In a way, yeah.", "在某种程度上，是的。"),
    ]
    for index, (english, chinese) in enumerate(samples, 1):
        subtitle_id = f"S{index:04d}"
        group_id = f"G{index:04d}"
        editor._last_semantic_group_audit_contexts = {
            group_id: _semantic_context(index, [subtitle_id], english, chinese)
        }
        editor._last_semantic_group_id_by_subtitle_id = {subtitle_id: group_id}
        segment = ASRDataSeg(english, index * 1000, index * 1000 + 800, chinese)
        segment.subtitle_id = subtitle_id

        issues = editor._chinese_semantic_group_audit_issues([segment], "WARNING")

        assert not issues


def test_allocation_validator_retries_multi_signal_chinese_boundary_issue():
    editor = _editor()
    entry = {
        "id": 31,
        "full_english": "The risk appears if markets continue rising.",
        "full_translation": "如果市场继续上涨，风险就会出现。",
        "subtitle_parts": [
            {"subtitle_id": "S0201", "english": "The risk appears if"},
            {"subtitle_id": "S0202", "english": "markets continue rising."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0201": "风险在于如果",
            "S0202": "市场继续上涨，就会出现。",
        },
    )

    assert validation["valid"] is False
    assert "modifier_head_split" in validation["issue_codes"]
    assert "punctuation_discontinuity" in validation["issue_codes"]


def test_semantic_audit_context_requires_id_signature_and_expected_ids():
    editor = _editor()
    context = _semantic_context(24, ["S0101", "S0102"], "Meta, the American tech giant.", "甲")
    editor._last_semantic_group_audit_contexts = {"G0024": context}
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0101": "G0024",
        "S0102": "G0024",
        "S9999": "G0099",
    }

    matched = editor._semantic_audit_context_for_group(
        "Meta, the American tech giant.",
        ["S0101", "S0102"],
    )
    assert matched["mapping_valid"] is True
    assert matched["semantic_group_id"] == "G0024"

    mismatch = editor._semantic_audit_context_for_group(
        "Meta, the American tech giant.",
        ["S0101", "S9999"],
    )
    assert mismatch["mapping_valid"] is False


def test_semantic_audit_mapping_does_not_shift_when_audit_groups_exceed_generation_count():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
        "G0002": _semantic_context(2, ["S0002"], "Bravo two.", "乙二"),
        "G0003": _semantic_context(3, ["S0003"], "Charlie three.", "丙三"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0001": "G0001",
        "S0002": "G0002",
        "S0003": "G0003",
    }
    checks = [
        editor._semantic_audit_context_for_group("Alpha one.", ["S0001"]),
        editor._semantic_audit_context_for_group("Exactly.", ["S9998"]),
        editor._semantic_audit_context_for_group("Bravo two.", ["S0002"]),
        editor._semantic_audit_context_for_group("Charlie three.", ["S0003"]),
        editor._semantic_audit_context_for_group("Right.", ["S9999"]),
    ]

    assert [checks[index]["semantic_group_id"] for index in (0, 2, 3)] == ["G0001", "G0002", "G0003"]
    assert [checks[index]["mapping_valid"] for index in (0, 2, 3)] == [True, True, True]
    assert checks[1]["mapping_valid"] is False
    assert checks[4]["mapping_valid"] is False


def test_semantic_audit_mapping_does_not_shift_when_audit_groups_drop_generation_count():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
        "G0002": _semantic_context(2, ["S0002"], "Bravo two.", "乙二"),
        "G0003": _semantic_context(3, ["S0003"], "Charlie three.", "丙三"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0001": "G0001",
        "S0002": "G0002",
        "S0003": "G0003",
    }
    checks = [
        editor._semantic_audit_context_for_group("Alpha one. Bravo two.", ["S0001", "S0002"]),
        editor._semantic_audit_context_for_group("Charlie three.", ["S0003"]),
    ]

    assert checks[0]["mapping_valid"] is False
    assert checks[1]["mapping_valid"] is True
    assert checks[1]["semantic_group_id"] == "G0003"


def test_repeated_short_dialogue_does_not_map_to_wrong_semantic_group():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0024": _semantic_context(24, ["S0247"], "Exactly.", "完全正确。"),
        "G0025": _semantic_context(25, ["S0248"], "Right.", "对。"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0247": "G0024", "S0248": "G0025"}
    context = editor._semantic_audit_context_for_group("Exactly.", ["S9999"])
    assert context["mapping_valid"] is False
    assert context.get("semantic_group_id", "") == ""


def test_missing_semantic_group_id_only_invalidates_that_group():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
        "G0003": _semantic_context(3, ["S0003"], "Charlie three.", "丙三"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {
        "S0001": "G0001",
        "S0003": "G0003",
    }
    groups = [("Alpha one.", ["S0001"]), ("Bravo two.", ["S0002"]), ("Charlie three.", ["S0003"])]
    results = [editor._semantic_audit_context_for_group(english, ids) for english, ids in groups]
    assert results[0]["mapping_valid"] is True
    assert results[1]["mapping_valid"] is False
    assert results[2]["mapping_valid"] is True
    assert results[2]["semantic_group_id"] == "G0003"


def test_identical_english_but_different_subtitle_ids_do_not_match():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0010": _semantic_context(10, ["S0101"], "Right.", "对。"),
        "G0011": _semantic_context(11, ["S0102"], "Right.", "没错。"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0101": "G0010", "S0102": "G0011"}
    matched = editor._semantic_audit_context_for_group("Right.", ["S0102"])
    assert matched["semantic_group_id"] == "G0011"
    mismatch = editor._semantic_audit_context_for_group("Right.", ["S0101", "S0102"])
    assert mismatch["mapping_valid"] is False


def test_g0248_full_translation_can_be_retraced_from_generated_context():
    editor = _editor()
    context = _semantic_context(
        248,
        ["S0391"],
        "All of it.",
        "所有的。"
    )
    editor._last_semantic_group_audit_contexts = {"G0248": context}
    editor._last_semantic_group_id_by_subtitle_id = {"S0391": "G0248"}
    matched = editor._semantic_audit_context_for_group("All of it.", ["S0391"])
    assert matched["semantic_group_id"] == "G0248"
    assert matched["full_translation"] == "所有的。"


def test_validation_report_full_translation_uses_single_stage_raw_records_for_all_valid_groups():
    editor = _id_editor()
    editor.model = "unit-test"
    editor.timeout = 1
    items = editor._assign_global_subtitle_ids(_id_items(5, translated="old-S{index:04d}"))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 6)]
    stale_full_translations = {
        index: f"stale-full-G{index:04d}"
        for index in range(1, 6)
    }
    editor._last_semantic_full_translations = dict(stale_full_translations)
    editor._last_semantic_group_audit_contexts = editor._semantic_group_audit_contexts(
        groups,
        stale_full_translations,
    )
    raw_groups = [
        {
            "id": index,
            "full_translation": f"raw-full-G{index:04d}",
            "part_translations": [
                {"subtitle_id": f"S{index:04d}", "zh": f"zh-S{index:04d}"}
            ],
        }
        for index in (3, 1, 5, 2, 4)
    ]
    editor.cache_manager = _StaticCache({"groups": raw_groups})

    applied = editor._translate_semantic_subtitle_groups_single_stage(items, groups)
    raw_by_semantic_group_id = {
        f"G{int(group['id']):04d}": group["full_translation"]
        for group in raw_groups
    }
    segments = []
    for index, item in enumerate(applied, 1):
        segment = ASRDataSeg(item.original, index * 1000, index * 1000 + 800, item.translated)
        segment.subtitle_id = item.subtitle_id
        segments.append(segment)

    def forced_findings(english, chinese, parts, full_translation="", mapping_valid=False):
        if not mapping_valid:
            return []
        return [
            {
                "code": "semantic_loss",
                "message": "forced semantic issue",
                "confidence_score": 0.9,
            }
        ]

    with patch.object(
        editor,
        "_semantic_segment_groups",
        return_value=[(0, 1), (0, 2), (1, 2), (2, 3), (3, 4), (4, 5)],
    ), patch.object(editor, "_chinese_group_quality_findings", side_effect=forced_findings):
        issues = editor._chinese_semantic_group_audit_issues(segments, "WARNING")

    valid_issues = [issue for issue in issues if issue.get("mapping_valid")]
    assert len(valid_issues) == 5
    for issue in valid_issues:
        semantic_group_id = issue["semantic_group_id"]
        assert issue["full_translation"] == raw_by_semantic_group_id[semantic_group_id]
        assert not issue["full_translation"].startswith("stale-full")
    assert any(not issue.get("mapping_valid") for issue in issues)


def test_mapping_failure_does_not_emit_full_translation_dependent_false_positive():
    editor = _editor()
    editor._last_semantic_group_audit_contexts = {
        "G0001": _semantic_context(1, ["S0001"], "Alpha one.", "甲一"),
    }
    editor._last_semantic_group_id_by_subtitle_id = {"S0001": "G0001"}
    issues = editor._chinese_semantic_group_audit_issues(
        [ASRDataSeg("Unmapped group.", 0, 1000, "孤立中文")],
        "WARNING",
    )
    assert all("semantic_loss" not in issue.get("reason", "") for issue in issues)


def test_command_chinese_audit_catches_confirmed_bad_groups():
    cues = [
        CaptionCue(106, 1, 2, "which leaves you,", "\u8fd9\u8ba9\u4f60\uff0c", ()),
        CaptionCue(
            107,
            2,
            3,
            "the listener, with a really unsettling thought to chew on long after",
            "\u542c\u4f17\uff0c\u7559\u4e0b\u4e86\u4e00\u4e2a\u975e\u5e38\u4ee4\u4eba\u4e0d\u5b89\u7684\u601d\u8003\uff0c\u4e45\u4e45",
            (),
        ),
        CaptionCue(108, 3, 4, "this deep dive is over.", "\u8fd9\u6b21\u6df1\u5ea6\u89e3\u6790\u7ed3\u675f\u540e\u3002", ()),
    ]

    issues = _chinese_semantic_group_issues(cues, "WARNING")

    assert issues
    assert "dangling_preposition" in issues[0]["rule_codes"]


def test_command_chinese_audit_ignores_normal_short_groups():
    cues = [
        CaptionCue(1, 1, 2, "Bouncing the sunlight away.", "\u628a\u9633\u5149\u53cd\u5c04\u56de\u53bb\u3002", ()),
        CaptionCue(2, 2, 3, "Oh, yeah.", "\u54e6\uff0c\u662f\u7684\u3002", ()),
    ]

    assert not _chinese_semantic_group_issues(cues, "WARNING")


def test_very_short_subtitle_has_dedicated_duration_error():
    editor = _editor()
    segments = [ASRDataSeg("Really?", 132200, 132300, "\u771f\u7684\u5417\uff1f")]

    issues = editor._subtitle_duration_issues(segments, "ERROR")

    assert issues
    assert issues[0]["code"] == "subtitle_duration_invalid"
    assert issues[0]["subtitle_id"] == "S0001"
    assert issues[0]["duration_ms"] == 100


def test_short_backchannel_duration_is_warning_not_error():
    editor = _editor()
    segments = [ASRDataSeg("Right.", 130140, 130360, "\u6ca1\u9519\u3002")]

    errors = editor._subtitle_duration_issues(segments, "ERROR")
    warnings = editor._subtitle_duration_issues(segments, "WARNING")

    assert not errors
    assert warnings
    assert warnings[0]["code"] == "subtitle_duration_too_short"
    assert warnings[0]["duration_ms"] == 220


def test_short_regular_sentence_duration_remains_error():
    editor = _editor()
    segments = [
        ASRDataSeg(
            "This sentence is too long.",
            1000,
            1220,
            "\u8fd9\u53e5\u8bdd\u592a\u957f\u4e86\u3002",
        )
    ]

    issues = editor._subtitle_duration_issues(segments, "ERROR")

    assert issues
    assert issues[0]["code"] == "subtitle_duration_invalid"
    assert issues[0]["duration_ms"] == 220


def test_asr_suspicious_phrases_are_reported_without_fixing_text():
    editor = _editor()
    segments = [
        ASRDataSeg("That caught me total off guard.", 1000, 3000, "ok"),
        ASRDataSeg("Seeds away the mirror.", 4000, 6000, "ok"),
        ASRDataSeg("It is geographing arbitrage.", 7000, 9000, "ok"),
        ASRDataSeg("They need stronger safety nuts.", 10000, 12000, "ok"),
        ASRDataSeg("A state-of the-art system arrived.", 13000, 15000, "ok"),
    ]

    issues = editor._asr_suspicious_issues(segments)
    codes = {issue.get("rule_code") for issue in issues}

    assert "asr_ungrammatical_collocation" in codes
    assert "asr_semantic_nonsense" in codes
    assert "asr_hyphenation_suspicious" in codes


def test_asr_suspicious_article_context_misses_are_reported():
    editor = _editor()
    segments = [
        ASRDataSeg("And the invisible electric cess was still there?", 0, 1200, "ok"),
        ASRDataSeg("Only 10% of America respondents said yes.", 1300, 2600, "ok"),
        ASRDataSeg("Taylor Swift plans to legally adopt Kils surname.", 2700, 4200, "ok"),
    ]

    issues = editor._asr_suspicious_issues(segments)
    codes = {issue.get("rule_code") for issue in issues}

    assert "asr_semantic_nonsense" in codes
    assert "asr_adjective_form_suspicious" in codes
    assert "asr_name_suspicious" in codes


def test_asr_suspicious_issues_are_bound_to_frozen_subtitle_ids():
    editor = _editor()
    segment = ASRDataSeg("That caught me total off guard.", 1000, 3000, "ok")
    segment.subtitle_id = "S0042"

    issues = editor._asr_suspicious_issues([segment])

    assert issues
    assert {issue["subtitle_id"] for issue in issues} == {"S0042"}


def test_abbreviation_name_boundary_is_syntax_warning():
    editor = _editor()

    assert "abbreviation_name_split" in editor._syntax_boundary_reasons("St.", "Gallen is a city.")
    assert "abbreviation_name_split" in _syntax_boundary_reasons("Dr.", "Smith explains it.")


def test_terminal_punctuation_wins_over_token_only_determiner_heuristic():
    words = "The team built a laboratory for this. They gathered 55 940 sentences.".split()
    editor = _marker_editor(words, max_words=16)
    this_index = words.index("this.")

    evaluation = editor._evaluate_stable_cut_boundary(this_index, this_index + 1)

    assert evaluation["legal"] is True
    assert evaluation["hard_issues"] == []
    assert evaluation["soft_issues"] == []
    assert not editor._is_unambiguous_sentence_terminal("Dr.", "Smith explains it.")


def test_lowercase_decade_suffix_is_terminal_but_name_initial_is_not():
    editor = _marker_editor(
        "They remember the late 2000 s. They moved on. J. Smith stayed.".split(),
        max_words=16,
    )

    spans = editor._stable_sentence_word_spans()
    texts = [editor._text_from_word_span(start, end) for start, end in spans]

    assert texts == [
        "They remember the late 2000 s.",
        "They moved on.",
        "J. Smith stayed.",
    ]
    assert editor._is_unambiguous_sentence_terminal("s.", "They moved on.")
    assert not editor._is_unambiguous_sentence_terminal("J.", "Smith stayed.")


def test_meridiem_period_is_not_terminal_inside_a_continuing_time_range():
    editor = _marker_editor(
        ["working", "9", "a", "m.", "to", "9", "p", "m."],
        max_words=16,
    )

    spans = editor._stable_sentence_word_spans()
    evaluation = editor._evaluate_stable_cut_boundary(3, 4)

    assert spans == [(0, 7)]
    assert not editor._is_unambiguous_sentence_terminal("m.", "to")
    assert not editor._is_unambiguous_sentence_terminal("a.m.", "to 9 p.m.")
    assert "time_range_continuation_split" in evaluation["hard_issues"]
    assert evaluation["legal"] is False


def test_pronoun_restart_is_not_misclassified_as_a_determiner_head_split():
    words = (
        "To understand the mechanics of this, you really have to look at the "
        "Chinese stock market ecosystem."
    ).split()
    editor = _marker_editor(words, max_words=16)
    this_index = words.index("this,")

    evaluation = editor._evaluate_stable_cut_boundary(this_index, this_index + 1)

    assert evaluation["legal"] is True
    assert "determiner_head_phrase_split" not in evaluation["hard_issues"]
    assert editor._is_determiner_head_phrase_split("the", "market") is True


def test_spaced_initialism_period_does_not_split_a_continuing_clause():
    text = (
        "Yes. The investor panic we are seeing in the U S. right now, "
        "the market blanching at Alphabet's budget, is understandable."
    )
    editor = _editor(max_words=16)
    editor._active_word_entries = _entries(text)
    surfaces = [entry["surface"] for entry in editor._active_word_entries]
    s_index = surfaces.index("S.")

    evaluation = editor._evaluate_stable_cut_boundary(s_index, s_index + 1)
    spans = editor._stable_sentence_word_spans()

    assert evaluation["legal"] is False
    assert "initialism_continuation_split" in evaluation["hard_issues"]
    assert all(end != s_index for _, end in spans)


def test_spaced_initialism_can_end_a_sentence_with_capitalized_restart_and_pause():
    text = "The team operates in the U S. This changes everything."
    editor = _editor(max_words=16)
    editor._active_word_entries = _entries(text)
    surfaces = [entry["surface"] for entry in editor._active_word_entries]
    s_index = surfaces.index("S.")
    shift_ms = 600 - (
        editor._active_word_entries[s_index + 1]["start_time"]
        - editor._active_word_entries[s_index]["end_time"]
    )
    for entry in editor._active_word_entries[s_index + 1 :]:
        entry["start_time"] += shift_ms
        entry["end_time"] += shift_ms

    evaluation = editor._evaluate_stable_cut_boundary(s_index, s_index + 1)

    assert "initialism_continuation_split" not in evaluation["hard_issues"]


def test_pronominal_appositive_prefers_the_complete_referent_at_an_alternative_cut():
    text = (
        "And going back to that opening stat about Moonshot AI, their K 3 model, "
        "the one that's 95% as clever but 70% cheaper."
    )
    editor = _editor(max_words=16)
    editor._active_word_entries = _entries(text)
    surfaces = [entry["surface"] for entry in editor._active_word_entries]
    model_index = surfaces.index("model,")
    pause_delta = 460 - (
        editor._active_word_entries[model_index + 1]["start_time"]
        - editor._active_word_entries[model_index]["end_time"]
    )
    for entry in editor._active_word_entries[model_index + 1 :]:
        entry["start_time"] += pause_delta
        entry["end_time"] += pause_delta

    evaluation = editor._evaluate_stable_cut_boundary(model_index, model_index + 1)
    ranges = editor._stable_word_ranges_for_span(
        (0, len(editor._active_word_entries) - 1)
    )
    selected_boundaries = {end for _, end in ranges[:-1]}

    assert "pronominal_appositive_referent_split" in evaluation["soft_issues"]
    assert model_index not in selected_boundaries
    assert any(
        "their K 3 model, the one" in editor._text_from_word_span(start, end)
        for start, end in ranges
    )


def test_caption_audit_uses_16_word_hard_limit():
    with tempfile.TemporaryDirectory() as temp_dir:
        srt = Path(temp_dir) / "soft-limit.srt"
        sixteen_words = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen."
        seventeen_words = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen."
        srt.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:04,000",
                    sixteen_words,
                    "十六词可以接受。",
                    "",
                    "2",
                    "00:00:04,000 --> 00:00:08,000",
                    seventeen_words,
                    "十七词超过硬上限。",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        report = audit_srt(srt)
    overlong = [issue for issue in report["errors"] if issue["code"] == "overlong_english"]

    assert len(overlong) == 1
    assert overlong[0]["index"] == 2
    assert overlong[0]["word_count"] == 17
    assert overlong[0]["hard_limit"] == 16


def test_caption_audit_accepts_allowed_plus_discourse_overflow():
    with tempfile.TemporaryDirectory() as temp_dir:
        srt = Path(temp_dir) / "plus-overflow.srt"
        srt.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:04,000",
                    "Plus, breaking away from corporate hubs kind of broke the social pressure to climb that traditional ladder.",
                    "此外，脱离企业中心也在一定程度上摆脱了传统晋升的社会压力。",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        report = audit_srt(srt)

    assert not [issue for issue in report["errors"] if issue["code"] == "overlong_english"]


def test_caption_audit_treats_borderline_chinese_speed_as_warning_not_blocker():
    with tempfile.TemporaryDirectory() as temp_dir:
        srt = Path(temp_dir) / "chinese-speed.srt"
        srt.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:01,340",
                    "I can see why you'd think that. I mean,",
                    "我理解你为什么这么想。我的意思是，",
                    "",
                    "2",
                    "00:00:02,000 --> 00:00:03,340",
                    "This is deliberately too dense.",
                    "这是一个故意设置得过于密集的中文字幕测试文本。",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        report = audit_srt(srt)

    speed_errors = [issue for issue in report["errors"] if issue["code"] == "chinese_speed_error"]
    speed_warnings = [issue for issue in report["warnings"] if issue["code"] == "chinese_speed_warning"]
    assert [issue["index"] for issue in speed_errors] == [2]
    assert [issue["index"] for issue in speed_warnings] == [1]


def test_caption_audit_uses_the_runtime_chinese_speed_error_boundary():
    with tempfile.TemporaryDirectory() as temp_dir:
        srt = Path(temp_dir) / "near-threshold-chinese-speed.srt"
        srt.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:01,241",
                    "A near-threshold cue.",
                    "一二三四五六七八九十一二三四五",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        report = audit_srt(srt)

    assert not [issue for issue in report["errors"] if issue["code"] == "chinese_speed_error"]
    assert [issue["index"] for issue in report["warnings"] if issue["code"] == "chinese_speed_warning"] == [1]


def test_caption_audit_keeps_numeric_percent_chinese_line():
    english, chinese = split_bilingual_body(["70%.", "70%。"])

    assert english == "70%."
    assert chinese == "70%。"


def test_large_number_anchor_variants_do_not_crash():
    variants = ScreenSubtitleEditor._chinese_number_anchor_variants("1000000000")

    assert variants


def test_concise_group_allocation_is_not_rejected_by_coverage_only():
    editor = _id_editor()
    entry = {
        "id": 96,
        "full_english": "So Beijing gets to look under the hood of Washington's best AI and vice versa.",
        "full_translation": "于是，北京可以了解华盛顿最优秀人工智能的内部情况，反之亦然。",
        "subtitle_parts": [
            {"subtitle_id": "S0152", "english": "So Beijing gets to look under the hood"},
            {"subtitle_id": "S0153", "english": "of Washington's best AI and vice versa."},
        ],
    }
    allocation = {
        "S0152": "于是，北京可窥华盛顿最优AI内部，",
        "S0153": "反之亦然。",
    }

    validation = editor._validate_group_chinese_allocation(entry, allocation)

    assert validation["valid"]
    assert "group_allocation_information_omission" not in validation["issue_codes"]

    stronger_compression = {
        "S0152": "于是，北京可窥探华盛顿顶尖AI内部",
        "S0153": "反之亦然。",
    }
    stronger_validation = editor._validate_group_chinese_allocation(
        entry, stronger_compression
    )

    assert stronger_validation["valid"]
    assert "group_allocation_information_omission" not in stronger_validation["issue_codes"]


def test_short_but_severe_chinese_speed_triggers_repair():
    editor = _id_editor()
    seg = ASRDataSeg(
        "simply can't patch?",
        0,
        1220,
        "无论如何也修补不了的漏洞，会发生什么？",
    )

    assert editor._is_severe_chinese_speed(seg)


def test_borderline_chinese_speed_does_not_trigger_render_blocker():
    editor = _id_editor()
    seg = ASRDataSeg(
        "I can see why you'd think that. I mean,",
        0,
        1340,
        "我理解你为什么这么想。我的意思是，",
    )

    # 15 Chinese characters / 1.34s = about 11.19 chars/s: review, not block.
    assert not editor._is_severe_chinese_speed(seg)


def test_short_subtitle_gets_minimum_display_duration_when_room_allows():
    segments = [
        ASRDataSeg("Exactly.", 18420, 18680, "ok"),
        ASRDataSeg("But what happens next?", 19560, 23280, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time - adjusted[0].start_time >= 800
    assert adjusted[0].end_time <= adjusted[1].start_time - 40


def test_short_backchannel_merges_with_following_segment():
    editor = _editor()
    segments = [
        ASRDataSeg("Exactly.", 37940, 38140, "ok"),
        ASRDataSeg("Okay, let's unpack this.", 38500, 40620, "ok"),
    ]

    merged = editor._merge_short_display_segments(segments)

    assert len(merged) == 1
    assert merged[0].text == "Exactly. Okay, let's unpack this."
    assert merged[0].start_time == 37940
    assert merged[0].end_time == 40620


def test_short_sentence_bridges_small_gap_before_next_subtitle():
    segments = [
        ASRDataSeg("It's wild.", 206140, 206660, "ok"),
        ASRDataSeg("Coming out for a second,", 208640, 212780, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time == adjusted[1].start_time - 40


def test_display_timing_bridges_regular_short_gap_before_next_subtitle():
    segments = [
        ASRDataSeg("That structural tightening is the key takeaway.", 1000, 4300, "ok"),
        ASRDataSeg("Better administration yields higher compliance.", 5020, 8200, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time == adjusted[1].start_time - 40
    assert adjusted[0].text == segments[0].text
    assert adjusted[1].start_time == segments[1].start_time


def test_display_timing_preserves_clear_long_pause():
    segments = [
        ASRDataSeg("That structural tightening is the key takeaway.", 1000, 4300, "ok"),
        ASRDataSeg("Better administration yields higher compliance.", 5600, 8200, "ok"),
    ]

    adjusted = ScreenSubtitleEditor._apply_display_timing_padding(segments)

    assert adjusted[0].end_time == segments[0].end_time + DISPLAY_TAIL_PADDING_MS
    assert adjusted[0].end_time < adjusted[1].start_time - 40
    assert adjusted[1].start_time == segments[1].start_time - DISPLAY_LEAD_IN_MS


def test_standalone_discourse_marker_attaches_to_immediate_next_sentence():
    editor = _marker_editor(["I", "mean,", "this", "market", "changed."])
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == "I mean, this market changed."
    assert editor._discourse_marker_orphans == []


def test_attached_oh_and_then_lead_in_merges_with_contiguous_clause():
    editor = _marker_editor(["Oh.", "And", "then", "the", "market", "changed."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 5, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert [item.original for item in merged] == ["Oh. And then the market changed."]
    assert editor._discourse_marker_orphans == []


def test_question_oh_lead_in_remains_independent():
    editor = _marker_editor(["Oh?", "And", "then", "what", "changed?"])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert [item.original for item in merged] == ["Oh?", "And then what changed?"]
    assert editor._discourse_marker_orphans


def test_oh_and_then_lead_in_respects_long_pause():
    editor = _marker_editor(["Oh.", "And", "then", "the", "market", "changed."])
    editor._active_word_entries[1]["start_time"] += 600
    editor._active_word_entries[1]["end_time"] += 600
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 5, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert [item.original for item in merged] == ["Oh.", "And then the market changed."]
    assert editor._discourse_marker_orphans


def test_oh_and_then_lead_in_respects_speaker_change():
    editor = _marker_editor(["Oh.", "And", "then", "the", "market", "changed."])
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 5, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert [item.original for item in merged] == ["Oh.", "And then the market changed."]
    assert editor._discourse_marker_orphans


def test_plus_marker_keeps_a_complete_one_word_overflow_unit():
    words = "Plus, breaking away from corporate hubs kind of broke the social pressure to climb that traditional ladder.".split()
    editor = _marker_editor(words, max_words=16)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, len(words) - 1, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == " ".join(words)
    assert ScreenSubtitleEditor._word_count(merged[0].original) == 17
    assert editor._is_allowed_plus_discourse_overflow(merged[0].original, 17, 16)


def test_oh_marker_attaches_to_next_complete_unit_at_one_word_overflow():
    words = [
        "Oh.", "And", "then", "they", "feed", "that", "curated,", "highly",
        "structured", "data", "to", "a", "new,", "smaller", "model,", "the",
        "student.",
    ]
    editor = _marker_editor(words, max_words=16)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, len(words) - 1, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == " ".join(words)
    assert ScreenSubtitleEditor._word_count(merged[0].original) == 17
    assert editor._is_allowed_plus_discourse_overflow(merged[0].original, 17, 16)


def test_trailing_standalone_discourse_marker_attaches_to_previous_sentence():
    editor = _marker_editor(["this", "market", "changed,", "you", "know."])
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 1
    assert merged[0].original == "this market changed, you know."
    assert editor._discourse_marker_orphans == []


def test_standalone_discourse_marker_does_not_cross_long_pause():
    editor = _marker_editor(["You", "know,", "this", "market", "changed."])
    editor._active_word_entries[2]["start_time"] = 1500
    editor._active_word_entries[2]["end_time"] = 1620
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert merged[0].original == "You know,"
    assert editor._discourse_marker_orphans
    assert editor._discourse_marker_orphans[0]["code"] == "discourse_marker_orphan"


def test_standalone_discourse_marker_does_not_cross_speaker_change():
    editor = _marker_editor(["I", "guess,", "this", "market", "changed."])
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert merged[0].original == "I guess,"
    assert editor._discourse_marker_orphans


def test_overlong_discourse_marker_attachment_reselects_cutpoint():
    content_words = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
    ]
    words = ["Well,", "I", "mean,"] + content_words
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 18, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert merged[0].original.startswith("Well, I mean, alpha")
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert merged[1].original == "golf hotel india juliet kilo lima mike november oscar papa"
    assert all(editor._standalone_discourse_marker(item.original) == "" for item in merged)
    assert editor._discourse_marker_orphans == []


def test_discourse_marker_rebalance_does_not_leave_one_word_fragment():
    content_words = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
        "mike",
    ]
    words = ["I", "mean,"] + content_words
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 14, 2)]

    merged = editor._merge_standalone_discourse_markers(items)

    assert len(merged) == 2
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert merged[0].original.startswith("I mean, alpha")
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_trailing_discourse_marker_is_not_left_at_subtitle_end():
    words = [
        "which",
        "is",
        "now,",
        "you",
        "know,",
        "a",
        "standard",
        "industry",
        "playbook.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 4, 1), _word_item(editor, 5, 8, 2)]

    rebalanced = editor._rebalance_edge_discourse_markers(items)

    assert len(rebalanced) == 2
    assert rebalanced[0].original == "which is now,"
    assert rebalanced[1].original == "you know, a standard industry playbook."
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in rebalanced)
    assert not editor._has_trailing_discourse_marker(rebalanced[0].original)


def test_discourse_marker_phrase_is_not_split_during_rebalance():
    words = [
        "which",
        "is",
        "now,",
        "you",
        "know,",
        "a",
        "standard",
        "industry",
        "playbook.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 4, 1), _word_item(editor, 5, 8, 2)]

    rebalanced = editor._rebalance_edge_discourse_markers(items)

    joined = " ".join(item.original for item in rebalanced)
    assert "you know" in joined.lower()
    assert all(not item.original.lower().endswith(" you") for item in rebalanced)
    assert all(not item.original.lower().startswith("know") for item in rebalanced)


def test_trailing_discourse_marker_rebalances_two_long_items_without_word_loss():
    words = [
        "this",
        "became",
        "the",
        "standard",
        "industry",
        "playbook,",
        "you",
        "know,",
        "because",
        "founders",
        "needed",
        "capital",
        "talent",
        "distribution",
        "and",
        "regulatory",
        "cover.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, 16, 2)]

    rebalanced = editor._rebalance_edge_discourse_markers(items)

    assert len(rebalanced) == 2
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in rebalanced)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in rebalanced)
    assert not editor._has_trailing_discourse_marker(rebalanced[0].original)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in rebalanced)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_short_yeah_rebalances_with_long_following_sentence():
    words = [
        "Yeah,",
        "they",
        "were",
        "clawing",
        "their",
        "way",
        "out",
        "of",
        "extreme",
        "poverty",
        "during",
        "China's",
        "early",
        "economic",
        "transition.",
    ]
    editor = _marker_editor(words, max_words=14)
    editor._active_word_entries[0]["end_time"] = 140
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 14, 2)]

    merged = editor._merge_short_display_segments(items)

    assert len(merged) == 2
    assert merged[0].original.startswith("Yeah, they were clawing")
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_short_though_attaches_to_following_sentence():
    editor = _marker_editor(["Though,", "it", "was", "different."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 3, 2)]

    merged = editor._merge_short_display_segments(items)

    assert len(merged) == 1
    assert merged[0].original == "Though, it was different."


def test_short_though_rebalances_without_leaving_orphan():
    words = [
        "Though,",
        "this",
        "generation",
        "still",
        "built",
        "durable",
        "companies",
        "through",
        "exports",
        "software",
        "capital",
        "discipline",
        "and",
        "constant",
        "pressure.",
    ]
    editor = _marker_editor(words, max_words=16)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 14, 2)]

    merged = editor._merge_short_display_segments(items)

    assert len(merged) == 1
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 16 for item in merged)
    assert all(item.original != "Though," for item in merged)
    assert all(ScreenSubtitleEditor._word_count(item.original) > 1 for item in merged)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_discourse_marker_ids_are_assigned_after_all_english_boundaries_are_fixed():
    editor = _marker_editor(["I", "mean,", "this", "market", "changed."])
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 4, 2)]
    assert all(item.subtitle_id is None for item in items)

    merged = editor._merge_standalone_discourse_markers(items)
    merged = editor._merge_short_display_segments(merged)
    assigned = editor._assign_global_subtitle_ids(merged)

    assert len(assigned) == 1
    assert assigned[0].subtitle_id == "S0001"
    assert assigned[0].original == "I mean, this market changed."


def test_discourse_marker_pre_id_pipeline_keeps_400_plus_english_chinese_id_sets_equal():
    words = [f"word{i}" for i in range(1, 406)]
    editor = _marker_editor(words, max_words=14)
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=f"English {index}.",
            translated=f"zh-S{index:04d}",
            word_start=index - 1,
            word_end=index - 1,
        )
        for index in range(1, 406)
    ]

    merged = editor._merge_standalone_discourse_markers(items)
    merged = editor._merge_short_display_segments(merged)
    assigned = editor._assign_global_subtitle_ids(merged)
    editor._validate_final_item_translation_ids(assigned)

    english_ids = [item.subtitle_id for item in assigned]
    chinese_ids = [item.subtitle_id for item in assigned if item.translated]
    assert len(assigned) == 405
    assert english_ids == [f"S{index:04d}" for index in range(1, 406)]
    assert english_ids == chinese_ids
    assert editor._translation_structure_errors == []


def test_discourse_marker_pre_id_pipeline_keeps_421_item_structure_errors_zero():
    words = [f"word{index}" for index in range(1, 422)]
    editor = _marker_editor(words, max_words=14)
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=f"English {index}.",
            translated=f"zh-S{index:04d}",
            word_start=index - 1,
            word_end=index - 1,
        )
        for index in range(1, 422)
    ]

    items = editor._merge_standalone_discourse_markers(items)
    items = editor._merge_short_display_segments(items)
    items = editor._rebalance_edge_discourse_markers(items)
    assigned = editor._assign_global_subtitle_ids(items)
    editor._validate_final_item_translation_ids(assigned)

    assert len(assigned) == 421
    assert len({item.subtitle_id for item in assigned}) == 421
    assert editor._translation_structure_errors == []


def test_balanced_split_does_not_create_preposition_object_boundary():
    words = [
        "Yeah,",
        "so",
        "Todd",
        "is",
        "the",
        "founder",
        "of",
        "a",
        "non-profit",
        "and",
        "the",
        "author",
        "of",
        "a",
        "book,",
        "which",
        "changed",
        "the",
        "field.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 18, 2)]

    merged = editor._merge_short_display_segments(items)

    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in merged)
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    for left, right in zip(merged, merged[1:]):
        assert "preposition_object_split" not in editor._evaluate_item_boundary(left, right)["hard_issues"]


def test_determiner_numeric_noun_boundary_is_hard_illegal():
    editor = _marker_editor(["those", "200", "economists", "signed", "the", "letter."])

    first = editor._evaluate_stable_cut_boundary(0, 1)
    second = editor._evaluate_stable_cut_boundary(1, 2)

    assert "determiner_numeric_noun_split" in first["hard_issues"]
    assert "determiner_numeric_noun_split" in second["hard_issues"]
    assert not first["legal"]
    assert not second["legal"]


def test_quantifier_phrase_boundary_is_hard_illegal():
    editor = _marker_editor(["a", "few", "thousand", "people", "arrived."])

    first = editor._evaluate_stable_cut_boundary(0, 1)
    second = editor._evaluate_stable_cut_boundary(1, 2)

    assert "quantifier_phrase_split" in first["hard_issues"]
    assert "quantifier_phrase_split" in second["hard_issues"]
    assert not first["legal"]
    assert not second["legal"]


def test_adverb_adjective_boundary_is_hard_illegal_without_pause():
    editor = _marker_editor(["a", "highly", "valuable", "company", "emerged."])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "adverb_adjective_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_short_verb_complement_boundary_is_hard_when_syntax_marks_it():
    editor = _marker_editor(["they", "made", "it", "quickly."])
    editor._record_syntax_hard_issue_for_indices([1, 2], "short_verb_complement_split")

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "short_verb_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_short_verb_possessive_complement_boundary_is_hard_when_syntax_marks_it():
    editor = _marker_editor(["he", "navigated", "his", "way", "carefully."])
    editor._record_syntax_hard_issue_for_indices([1, 2, 3], "short_verb_complement_split")

    first = editor._evaluate_stable_cut_boundary(1, 2)
    second = editor._evaluate_stable_cut_boundary(2, 3)

    assert "short_verb_complement_split" in first["hard_issues"]
    assert "short_verb_complement_split" in second["hard_issues"]
    assert not first["legal"]
    assert not second["legal"]


def test_parser_blocks_direct_verb_particle_boundary():
    editor = _marker_editor(
        ["AI", "is", "stepping", "in", "and", "permanently", "filling", "the", "gap."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "verb_particle_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_compact_coordinated_subject_boundary():
    editor = _marker_editor(
        ["why", "you", "and", "so", "many", "others", "support", "this", "change."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "coordinated_subject_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_compact_coordination_boundaries():
    predicate_editor = _marker_editor(
        "Yeah. As AI continues to rapidly adapt and, you know, successfully mimic our best writing traits, it changes.".split()
    )
    predicate_editor._prepare_syntax_cut_hints()

    predicate = predicate_editor._evaluate_stable_cut_boundary(9, 10)

    assert "coordinated_constituent_split" in predicate["hard_issues"]
    assert not predicate["legal"]

    list_editor = _marker_editor(
        "Yeah. Will you have to rely on deliberate eccentricity, messy grammar, and chaotic punctuation, just to prove it?".split()
    )
    list_editor._prepare_syntax_cut_hints()

    list_item = list_editor._evaluate_stable_cut_boundary(8, 9)

    assert "coordinated_constituent_split" in list_item["hard_issues"]
    assert not list_item["legal"]


def test_parser_blocks_object_content_clause_boundary():
    editor = _marker_editor(
        "Well, if you are relying on Pangram to tell you if an email or an essay is real, you have to understand this.".split()
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(9, 10)

    assert "object_content_clause_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_object_attached_modifier_boundary():
    editor = _marker_editor(
        "They are constantly adjusting their internal weights based on human thumbs-ups and thumbs-downs.".split()
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(6, 7)

    assert "object_attached_modifier_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_keeps_clause_scope_adverb_with_following_subordinator():
    words = (
        "They are deliberately driving up this box office specifically because "
        "the plot is incomprehensible and the animation is shockingly terrible."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    specifically_index = words.index("specifically")
    because_index = words.index("because")

    evaluation = editor._evaluate_stable_cut_boundary(
        specifically_index,
        because_index,
    )
    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))
    rendered = [" ".join(words[start : end + 1]) for start, end in ranges]

    assert "clause_scope_modifier_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]
    assert rendered == [
        "They are deliberately driving up this box office",
        "specifically because the plot is incomprehensible and the animation is shockingly terrible.",
    ]


def test_parser_clause_scope_modifier_guard_has_general_positive_and_negative_cases():
    protected_cases = [
        ("They rejected it just because the timing was wrong.", "just", "because"),
        ("We changed course only because the evidence shifted.", "only", "because"),
        (
            "They continued specifically although the risk remained.",
            "specifically",
            "although",
        ),
    ]
    for text, modifier, marker in protected_cases:
        words = text.split()
        editor = _marker_editor(words)
        editor._prepare_syntax_cut_hints()

        evaluation = editor._evaluate_stable_cut_boundary(
            words.index(modifier),
            words.index(marker),
        )

        assert "clause_scope_modifier_split" in evaluation["hard_issues"]
        assert not evaluation["legal"]

    punctuated_words = (
        "They discussed it specifically, because the timing mattered."
    ).split()
    punctuated_editor = _marker_editor(punctuated_words)
    punctuated_editor._prepare_syntax_cut_hints()
    punctuated = punctuated_editor._evaluate_stable_cut_boundary(
        punctuated_words.index("specifically,"),
        punctuated_words.index("because"),
    )

    assert "clause_scope_modifier_split" not in punctuated["hard_issues"]


def test_parser_blocks_misattached_zero_relative_clause_boundary():
    editor = _marker_editor(
        (
            "And it brings us to one of the most fascinating technical strategies "
            "in the sources we're looking at today."
        ).split()
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(14, 15)

    assert "zero_relative_clause_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_cross_cue_dependency_units_from_oil_run():
    cases = [
        (
            "Brent crude is sitting about 40 below its April 30 th intraday high of 126 a barrel.",
            "th",
            "intraday",
            "date_nominal_continuation_split",
        ),
        (
            "And surprisingly, Iran has found itself with far less leverage over Donald Trump than anyone anticipated heading into this.",
            "Trump",
            "than",
            "comparative_clause_split",
        ),
        (
            "Because when you hear that one-fifth of the world's oil supply is suddenly trapped behind a blockade, your immediate expectation is just total panic, right?",
            "supply",
            "is",
            "subject_finite_verb_split",
        ),
        (
            "Usually, China imports crude, refines it, and exports a lot of finished diesel and gasoline for profit.",
            "exports",
            "a",
            "short_verb_object_split",
        ),
        (
            "They basically commanded heavy industry to dial back consumption during the exact window the strait was shut.",
            "window",
            "the",
            "zero_relative_clause_split",
        ),
        (
            "It makes it impossible for America and others to know how long they can withstand sanctions or war.",
            "long",
            "they",
            "embedded_wh_clause_split",
        ),
        (
            "But the relief of a 2026 superglut masks a much more dangerous long-term reality regarding global supply and demand, doesn't it?",
            "reality",
            "regarding",
            "dependency_phrase_entrance_split",
        ),
        (
            "why are so many other nations still acting as if the current oil dependent system will last forever?",
            "acting",
            "as",
            "clause_complement_entrance_split",
        ),
    ]

    for text, left_surface, right_surface, expected_issue in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        left = next(
            index
            for index, (current, following) in enumerate(zip(words, words[1:]))
            if current == left_surface and following == right_surface
        )

        evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

        assert expected_issue in evaluation["hard_issues"], text
        assert not evaluation["legal"], text


def test_parser_blocks_dreamcore_cross_cue_dependency_continuations():
    cases = [
        (
            "Right. We are taking a deep dive today into our source material.",
            "dive",
            "today",
            "predicate_attached_continuation_split",
        ),
        (
            "And looking at the sheer scale of this, it is clear this isn't a passing trend.",
            "clear",
            "this",
            "content_clause_entrance_split",
        ),
        (
            "The room had with like this sickly yellow wallpaper an eerie glow.",
            "like",
            "this",
            "preposition_object_split",
        ),
        (
            "What pushes it over the edge into that aesthetic is the sound.",
            "edge",
            "into",
            "predicate_attached_continuation_split",
        ),
        (
            "It's almost like a weighted blanket.",
            "almost",
            "like",
            "dependency_phrase_entrance_split",
        ),
        (
            "You have gleaming megacities right next to forgotten cities.",
            "megacities",
            "right",
            "predicate_attached_continuation_split",
        ),
        (
            "The Canadian philosopher Marshall McLuhan captured this mechanism.",
            "philosopher",
            "Marshall",
            "appositive_name_split",
        ),
        (
            "They could not choose their own path forward in reality.",
            "path",
            "forward",
            "predicate_attached_continuation_split",
        ),
    ]

    for text, left_surface, right_surface, expected_issue in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        left = next(
            index
            for index, (current, following) in enumerate(zip(words, words[1:]))
            if current == left_surface and following == right_surface
        )

        evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

        assert expected_issue in evaluation["hard_issues"], (text, evaluation)
        assert not evaluation["legal"], text


def test_parser_does_not_treat_parallel_common_noun_list_as_name_apposition():
    text = (
        "The system monitors the origin of every component, the digital routing "
        "of every container, and the nationality of the capital."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    left = words.index("component,")

    evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

    assert "appositive_name_split" not in evaluation["hard_issues"]


def test_dreamcore_dependency_continuation_guard_respects_sentence_and_pause():
    sentence_cases = [
        ("The result is clear. This is final.", "clear.", "This"),
        ("She read the Canadian philosopher. Marshall called later.", "philosopher.", "Marshall"),
        ("They reached the edge. Into the valley they went.", "edge.", "Into"),
    ]
    for text, left_surface, right_surface in sentence_cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        left = next(
            index
            for index, (current, following) in enumerate(zip(words, words[1:]))
            if current == left_surface and following == right_surface
        )

        evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

        assert evaluation["legal"], (text, evaluation)

    words = "They chose their path forward after a long pause.".split()
    editor = _marker_editor(words, max_words=16)
    boundary = words.index("path")
    for entry in editor._active_word_entries[boundary + 1 :]:
        entry["start_time"] += 600
        entry["end_time"] += 600
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(boundary, boundary + 1)

    assert "predicate_attached_continuation_split" not in evaluation["hard_issues"]


def test_dreamcore_pre_id_repair_does_not_create_attached_one_word_or_new_overflow():
    text = (
        "Yeah. An anonymous user posted a simple photograph of an empty carpeted "
        "room with like this sickly yellow wallpaper and the buzzing glare of "
        "fluorescent lights."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    cut_after = words.index("like")
    original = [
        _word_item(editor, 0, cut_after, 1),
        _word_item(editor, cut_after + 1, len(words) - 1, 1),
    ]
    original_counts = [editor._word_count(item.original) for item in original]
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    evaluation = editor._evaluate_item_pair_for_final_boundary(
        original[0],
        original[1],
    )
    repaired = editor._validate_and_repair_final_pre_id_boundaries(original)

    assert "preposition_object_split" in evaluation["hard_issues"]
    assert editor._items_word_tokens(repaired) == editor._items_word_tokens(original)
    assert all(item.original != "Yeah." for item in repaired)
    assert max(editor._word_count(item.original) for item in repaired) <= max(
        max(original_counts), editor.max_english_words
    )
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def test_dreamcore_dependency_cases_finalize_without_hard_english_cuts():
    cases = [
        (
            "Right. We are taking a deep dive today into our source material "
            "to explore a massive internet phenomenon known as Chinese Dream Corps.",
            "predicate_attached_continuation_split",
        ),
        (
            "And looking at the sheer scale of this, it is clear this isn't "
            "just some passing art trend.",
            "content_clause_entrance_split",
        ),
        (
            "Yeah. An anonymous user posted a simple photograph of an empty "
            "carpeted room with like this sickly yellow wallpaper and the "
            "buzzing glare of fluorescent lights.",
            "preposition_object_split",
        ),
        (
            "But what pushes it over the edge into that Dreamcore aesthetic is "
            "how those synths are amplified by audio samples of children "
            "playing in the distance.",
            "predicate_attached_continuation_split",
        ),
        (
            "It's almost like a psychological weighted blanket woven out of "
            "old CRT TVs and fading playground equipment.",
            "dependency_phrase_entrance_split",
        ),
        (
            "Yeah. You have gleaming megacities right next to forgotten Tier 4 "
            "cities where time seemingly stopped decades ago.",
            "predicate_attached_continuation_split",
        ),
        (
            "If we connect this to the bigger picture, the Canadian philosopher "
            "Marshall McLuhan captured this mechanism perfectly in his book, "
            "The Medium is the Massage.",
            "appositive_name_split",
        ),
        (
            "Wow. When an entire generation feels completely unable to choose "
            "their own path forward in a hyper-competitive reality, the past "
            "becomes the ultimate refuge.",
            "predicate_attached_continuation_split",
        ),
    ]

    for text, prohibited_issue in cases:
        editor = _marker_editor(text.split(), max_words=16)
        word_times_before = [
            (entry["start_time"], entry["end_time"])
            for entry in editor._active_word_entries
        ]

        finalized = editor._finalize_stable_english_boundaries([])

        assert editor._items_word_tokens(finalized) == [
            editor._clean_boundary_token(entry["token"])
            for entry in editor._active_word_entries
        ], text
        assert all(
            prohibited_issue
            not in editor._evaluate_item_pair_for_final_boundary(left, right)[
                "hard_issues"
            ]
            for left, right in zip(finalized, finalized[1:])
        ), text
        assert not any(
            editor._word_count(left.original) == 1
            and editor._is_short_backchannel_text(left.original)
            and editor._word_count(right.original) > editor.max_english_words + 3
            for left, right in zip(finalized, finalized[1:])
        ), text
        assert [
            (entry["start_time"], entry["end_time"])
            for entry in editor._active_word_entries
        ] == word_times_before


def test_dreamcore_terminal_elliptical_answer_merges_before_ids_with_context():
    text = (
        "Oh, definitely. In New Jean's music videos, and even in video games, "
        "like the upcoming walking simulator, literally titled Dreamcore. "
        "Exactly."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    previous = _word_item(editor, 0, 1, 1)
    left = _word_item(editor, 2, 11, 2)
    right = _word_item(editor, 12, 19, 3)
    following = _word_item(editor, 20, 20, 4)
    items = [previous, left, right, following]

    evaluation = editor._evaluate_item_pair_for_final_boundary(
        left,
        right,
        previous,
    )
    repaired = editor._repair_pre_id_boundary_window(items, 1, evaluation)

    assert "leading_prepositional_fragment" in evaluation["hard_issues"]
    assert repaired is not None
    start, end, replacement, _ = repaired
    assert (start, end) == (1, 3)
    assert len(replacement) == 1
    assert replacement[0].original == (
        "In New Jean's music videos, and even in video games, like the "
        "upcoming walking simulator, literally titled Dreamcore."
    )
    assert editor._items_word_tokens(replacement) == editor._items_word_tokens(
        [left, right]
    )


def test_terminal_prepositional_fragment_without_short_answer_stays_blocked():
    text = (
        "The team stopped. In local music videos, and even in video games, "
        "like the upcoming walking simulator, literally titled Dreamcore."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    previous = _word_item(editor, 0, 2, 1)
    merged = _word_item(editor, 3, len(words) - 1, 2)

    fragment = editor._evaluate_final_display_fragment(
        merged,
        previous,
        None,
    )

    assert "leading_prepositional_fragment" in fragment["hard_fragment_issues"]


def test_terminal_affirmation_attaches_to_following_clause_before_ids():
    text = (
        "The evidence shows this change affects an entire generation facing "
        "unprecedented pressure. Absolutely. And listeners everywhere can "
        "relate to modern burnout."
    )
    editor = _marker_editor(text.split(), max_words=16)

    finalized = editor._finalize_stable_english_boundaries([])

    assert [item.original for item in finalized] == [
        "The evidence shows this change affects an entire generation facing "
        "unprecedented pressure.",
        "Absolutely. And listeners everywhere can relate to modern burnout.",
    ]


def test_open_subordinate_prefix_merges_with_its_main_clause_before_ids():
    text = (
        "Yeah. Because if you actually look closely at these meticulously "
        "reconstructed digital environments, you realize something shocking."
    )
    editor = _marker_editor(text.split(), max_words=16)

    finalized = editor._finalize_stable_english_boundaries([])

    assert [item.original for item in finalized] == [
        "Yeah.",
        "Because if you actually look closely at these meticulously "
        "reconstructed digital environments, you realize something shocking.",
    ]
    assert editor._word_count(finalized[1].original) == 16
    assert not editor._is_open_subordinate_prefix(finalized[1])
    assert editor._items_word_tokens(finalized) == [
        editor._clean_boundary_token(entry["token"])
        for entry in editor._active_word_entries
    ]


def test_cross_cue_dependency_guards_keep_independent_boundaries_legal():
    cases = [
        ("If prices rise, how should consumers respond?", "rise,", "how"),
        ("For my entire life, we were taught to expect scarcity.", "life,", "we"),
        ("If China checks out entirely, the rest of the market adapts.", "entirely,", "the"),
        ("Supply tightened, but demand remained strong.", "tightened,", "but"),
        ("They met on April 30 th. Intraday trading resumed later.", "th.", "Intraday"),
        ("The plan was impossible. For America, that changed everything.", "impossible.", "For"),
    ]

    for text, left_surface, right_surface in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        left = next(
            index
            for index, (current, following) in enumerate(zip(words, words[1:]))
            if current == left_surface and following == right_surface
        )

        evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

        assert evaluation["legal"], (text, evaluation)


def test_final_pre_id_repairs_oil_dependency_boundaries_without_word_loss():
    cases = [
        (
            "Brent crude is sitting about 40 below its April 30 th intraday high of 126 a barrel.",
            "th",
            [17],
        ),
        (
            "And surprisingly, Iran has found itself with far less leverage over Donald Trump than anyone anticipated heading into this.",
            "Trump",
            [19],
        ),
        (
            "Because when you hear that one-fifth of the world's oil supply is suddenly trapped behind a blockade, your immediate expectation is just total panic, right?",
            "supply",
            [25],
        ),
        (
            "Usually, China imports crude, refines it, and exports a lot of finished diesel and gasoline for profit.",
            "exports",
            [17],
        ),
        (
            "They basically commanded heavy industry to dial back consumption during the exact window the strait was shut.",
            "window",
            [17],
        ),
        (
            "It makes it impossible for America and others to know how long they can withstand sanctions or war.",
            "long",
            [18],
        ),
        (
            "But the relief of a 2026 superglut masks a much more dangerous long-term reality regarding global supply and demand, doesn't it?",
            "reality",
            [21],
        ),
        (
            "why are so many other nations still acting as if the current oil dependent system will last forever?",
            "acting",
            [18],
        ),
    ]

    for text, left_surface, expected_counts in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        cut = words.index(left_surface)
        items = [
            _word_item(editor, 0, cut, 1),
            _word_item(editor, cut + 1, len(words) - 1, 2),
        ]
        original_tokens = editor._items_word_tokens(items)

        repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

        assert [editor._word_count(item.original) for item in repaired] == expected_counts, text
        assert editor._items_word_tokens(repaired) == original_tokens, text
        assert all(not item.subtitle_id for item in repaired), text
        assert all(
            editor._evaluate_item_pair_for_final_boundary(left, right)["legal"]
            for left, right in zip(repaired, repaired[1:])
        ), text


def test_parser_blocks_clausal_subject_from_its_finite_predicate():
    words = (
        "But I'm looking at these sources, and they're arguing that being cut "
        "off from the most sophisticated chip-making gear is actually forcing "
        "these companies to become better engineers."
    ).split()
    editor = _marker_editor(words)
    editor._prepare_syntax_cut_hints()
    split = next(
        index
        for index in range(1, len(words))
        if words[index - 1] == "gear" and words[index] == "is"
    )

    evaluation = editor._evaluate_stable_cut_boundary(split - 1, split)

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_short_dative_object_start_boundary():
    editor = _marker_editor(
        ["the", "company", "gives", "you", "a", "completely", "different", "lens."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)

    assert "short_verb_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_numeric_range_boundaries():
    editor = _marker_editor(
        ["the", "stock", "plummeted", "from", "36%", "to", "under", "10%", "in", "June."]
    )
    editor._prepare_syntax_cut_hints()

    for cut_after in (2, 3, 4, 5, 6):
        evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)
        assert "numeric_range_split" in evaluation["hard_issues"], evaluation
        assert not evaluation["legal"]


def test_parser_keeps_an_extended_numeric_range_attached_to_its_to_connector():
    words = (
        "shipments growing from 15 million units this year to 28 million by 2030."
    ).split()
    editor = _marker_editor(words)
    editor._prepare_syntax_cut_hints()
    to_index = words.index("to")

    before_to = editor._evaluate_stable_cut_boundary(to_index - 1, to_index)
    after_to = editor._evaluate_stable_cut_boundary(to_index, to_index + 1)
    target_magnitude = editor._evaluate_stable_cut_boundary(
        words.index("28"), words.index("million", words.index("28"))
    )
    trailing_date = editor._evaluate_stable_cut_boundary(
        words.index("by"), words.index("2030.")
    )

    assert "numeric_range_split" in before_to["hard_issues"]
    assert "numeric_range_split" in after_to["hard_issues"]
    assert "numeric_range_split" in target_magnitude["hard_issues"]
    assert "numeric_range_split" not in trailing_date["hard_issues"]


def test_pre_id_candidate_gate_rejects_new_hard_syntax_boundary():
    editor = _marker_editor(["they", "made", "it", "to", "the", "top."], max_words=6)
    editor._prepare_syntax_cut_hints()
    old_items = [_word_item(editor, 0, 5)]
    candidate = [_word_item(editor, 0, 1), _word_item(editor, 2, 5)]

    decision = editor._can_apply_pre_id_repair_candidate(old_items, candidate)

    assert decision["accepted"] is False
    assert "short_verb_complement_split" in decision["hard_issues"]
    assert decision["old_word_range"] == decision["new_word_range"] == [0, 5]


def test_long_object_still_allows_legal_boundary():
    editor = _marker_editor(
        [
            "they",
            "built",
            "a",
            "large",
            "durable",
            "export",
            "business",
            "with",
            "capital",
            "partners",
            "over",
            "many",
            "years.",
        ]
    )

    evaluation = editor._evaluate_stable_cut_boundary(6, 7)

    assert evaluation["hard_issues"] == []
    assert evaluation["legal"]


def test_final_pre_id_repair_removes_known_hard_boundary():
    words = [
        "Todd",
        "is",
        "the",
        "founder",
        "of",
        "a",
        "non-profit",
        "and",
        "the",
        "author",
        "of",
        "a",
        "book",
        "about",
        "risk.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 4, 1), _word_item(editor, 5, 14, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in repaired)
    assert all(
        editor._evaluate_item_boundary(left, right)["legal"]
        for left, right in zip(repaired, repaired[1:])
    )
    assert editor._pre_id_boundary_repairs


def test_final_pre_id_blocks_content_noun_that_clause_boundary():
    words = ["The", "fact", "that", "the", "market", "changed", "matters."]
    editor = _marker_editor(words, max_words=14)
    editor._prepare_syntax_cut_hints()
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, len(words) - 1, 2)]

    evaluation = editor._evaluate_item_boundary(items[0], items[1])
    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert "content_noun_that_clause_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == (
        ScreenSubtitleEditor._word_tokens(" ".join(words))
    )
    assert all(
        "content_noun_that_clause_split"
        not in editor._evaluate_item_boundary(left, right)["hard_issues"]
        for left, right in zip(repaired, repaired[1:])
    )


def test_final_pre_id_keeps_discourse_marker_with_following_sentence_after_terminal_over():
    words = [
        "But", "the", "thing", "I", "keep", "coming", "back", "to", "is", "how",
        "fast", "this", "is", "evolving.", "I", "mean,", "the", "Delve", "era", "is",
        "over.", "Why", "does", "its", "style", "change", "so", "rapidly?",
    ]
    editor = _marker_editor(words, max_words=16)
    items = [
        _word_item(editor, 0, 13, 1),
        _word_item(editor, 14, 20, 2),
        _word_item(editor, 21, 27, 3),
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert repaired[1].original == "I mean, the Delve era is over."
    assert not any(item.original.endswith("I mean,") for item in repaired)
    assert "preposition_object_split" not in editor._evaluate_item_boundary(
        repaired[1], repaired[2]
    )["hard_issues"]


def test_final_pre_id_rebalances_leading_nonfinite_dependent_prefix():
    words = (
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to, "
        "so it doesn't need all those attributive commas and quotation marks either."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    # The real comma-scoped ellipted result clause has a 380ms pause.  It is
    # reviewable evidence, not a hard preposition/object split.
    for entry in editor._active_word_entries[11:]:
        entry["start_time"] += 300
        entry["end_time"] += 300
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, len(words) - 1, 2)]
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to,",
        "so it doesn't need all those attributive commas and quotation marks either.",
    ]
    assert [item.word_start for item in repaired] == [0, 11]
    assert [item.word_end for item in repaired] == [10, len(words) - 1]
    assert any(
        record["repair_reason"] == "leading_nonfinite_dependent_prefix_rebalanced"
        for record in editor._pre_id_boundary_repairs
    )
    assert editor._pre_id_boundary_repairs[0]["word_order_preserved"] is True
    assert editor._pre_id_boundary_repairs[0]["word_coverage_preserved"] is True
    for index, item in enumerate(repaired, 1):
        item.subtitle_id = f"S{index:04d}"
    editor._last_subtitle_items = list(repaired)
    segments = []
    for item in repaired:
        segment = ASRDataSeg(item.original, 0, 1000, "中文")
        segment.word_start = item.word_start
        segment.word_end = item.word_end
        segment.subtitle_id = item.subtitle_id
        segments.append(segment)
    assert editor._bad_cut_issues(segments) == []
    audit = editor._syntax_boundary_audit_issues(segments)
    assert len(audit) == 1
    assert audit[0]["classification"] == "review"
    assert audit[0]["recommended_action"] == "manual_review"
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def test_final_pre_id_keeps_finite_conditional_introduction_in_its_own_cue():
    words = (
        "The speaker sets up an example if I normally say, uh, "
        "I'm going to eat a sandwich for lunch."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    left = _word_item(editor, 0, 5, 1)
    right = _word_item(editor, 6, len(words) - 1, 2)

    assert editor._leading_nonfinite_dependent_prefix_end(right) is None
    assert editor._rebalance_leading_nonfinite_dependent_prefixes([left, right]) == [left, right]


def test_leading_nonfinite_dependent_prefix_rebalance_respects_long_pause():
    words = (
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to, "
        "so it doesn't need all those attributive commas and quotation marks either."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    for entry in editor._active_word_entries[8:]:
        entry["start_time"] += 600
        entry["end_time"] += 600
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, len(words) - 1, 2)]

    assert editor._rebalance_leading_nonfinite_dependent_prefixes(items) == items
    assert editor._pre_id_boundary_repairs == []


def test_leading_nonfinite_dependent_prefix_rebalance_respects_speaker_change():
    words = (
        "Exactly. Plus, it doesn't naturally quote human experts unless forced to, "
        "so it doesn't need all those attributive commas and quotation marks either."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 7, 1), _word_item(editor, 8, len(words) - 1, 2)]

    assert editor._rebalance_leading_nonfinite_dependent_prefixes(items) == items
    assert editor._pre_id_boundary_repairs == []


def test_final_pre_id_repair_does_not_cross_speaker_change():
    words = ["founder", "of", "a", "non-profit", "built", "trust."]
    editor = _marker_editor(words, max_words=14)
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert editor._pre_id_boundary_repairs[-1]["unresolved_hard_issue"] is True


def test_final_pre_id_rejects_noop_repartition_without_iteration_loop():
    editor = _marker_editor(["founder", "of", "a", "non-profit"], max_words=14)
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 3, 2)]
    evaluation = editor._evaluate_item_pair_for_final_boundary(items[0], items[1])
    assert not evaluation["legal"]

    with patch.object(
        editor,
        "_repartition_pre_id_window",
        return_value=(list(items), [{"cuts": [[1, 2]]}]),
    ):
        repaired = editor._repair_pre_id_boundary_window(items, 0, evaluation)

    assert repaired is None


def test_verb_directional_adverb_preposition_boundary_is_hard_when_syntax_marks_it():
    editor = _marker_editor(
        [
            "But",
            "the",
            "thing",
            "I",
            "keep",
            "coming",
            "back",
            "to",
            "is",
            "how",
            "fast",
            "this",
            "is",
            "evolving.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    verb_adverb = editor._evaluate_stable_cut_boundary(5, 6)
    adverb_preposition = editor._evaluate_stable_cut_boundary(6, 7)

    assert "verb_adverb_preposition_split" in verb_adverb["hard_issues"]
    assert "verb_adverb_preposition_split" in adverb_preposition["hard_issues"]
    assert not verb_adverb["legal"]
    assert not adverb_preposition["legal"]


def test_parser_dependency_phrase_entrances_are_hard_boundaries():
    cases = [
        (
            [
                "Yeah.", "And", "this", "is", "really", "the", "secret", "to", "how",
                "these", "developers", "are", "optimizing", "their", "costs.",
            ],
            6,
        ),
        (
            [
                "The", "student", "learns", "the", "underlying", "logic", "and", "patterns",
                "without", "needing", "the", "teacher.",
            ],
            7,
        ),
        (
            [
                "They", "launched", "an", "efficient", "model", "by", "investing", "heavily",
                "in", "techniques.",
            ],
            6,
        ),
        (
            [
                "You", "have", "to", "build", "something", "highly", "efficient", "that",
                "delivers", "a", "return.",
            ],
            6,
        ),
        (["They", "are", "so", "drastically", "optimizing", "costs."], 3),
    ]

    for words, cut_after in cases:
        editor = _marker_editor(words)
        editor._prepare_syntax_cut_hints()

        evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)

        assert "dependency_phrase_entrance_split" in evaluation["hard_issues"], words
        assert not evaluation["legal"], words


def test_spacy_alignment_keeps_ledger_words_after_a_split_contraction():
    words = (
        "You cannot untangle a hopelessly complex global supply chain without "
        "someone paying the bill."
    ).split()
    editor = _marker_editor(words)
    nlp = editor._load_syntax_nlp()
    assert nlp is not None
    doc = nlp(editor._normalize_text(" ".join(words)))

    mapping = editor._align_doc_tokens_to_word_entries(doc, 0, len(words) - 1)
    token_words = {
        token.text: mapping.get(token.i)
        for token in doc
        if not token.is_punct
    }

    assert token_words["can"] == words.index("cannot")
    assert token_words["not"] == words.index("cannot")
    assert token_words["supply"] == words.index("supply")
    assert token_words["chain"] == words.index("chain")


def test_parser_blocks_attached_clause_entrances_from_white_house_run():
    cases = [
        (
            "It's a completely normal scenario for anyone just walking down a store aisle today.",
            "anyone",
            "just",
        ),
        (
            "Free trade agreements include massive highly technical chapters called rules of origin.",
            "chapters",
            "called",
        ),
        (
            "The reason that extreme localized dragnet hasn't come to pass is a massive roadblock.",
            "come",
            "to",
        ),
    ]
    for text, left_surface, right_surface in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        left = next(
            index
            for index, (current, following) in enumerate(zip(words, words[1:]))
            if current == left_surface and following == right_surface
        )

        evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

        assert "dependency_phrase_entrance_split" in evaluation["hard_issues"], (
            text,
            evaluation,
        )
        assert not evaluation["legal"], text


def test_attached_clause_entrance_guard_allows_independent_sentence_starts():
    cases = [
        ("We stopped. To reduce costs, we automated.", "stopped.", "To"),
        ("The report ended. Called sources responded later.", "ended.", "Called"),
    ]
    for text, left_surface, right_surface in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        left = next(
            index
            for index, (current, following) in enumerate(zip(words, words[1:]))
            if current == left_surface and following == right_surface
        )

        evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

        assert "dependency_phrase_entrance_split" not in evaluation["hard_issues"]
        assert evaluation["legal"], (text, evaluation)


def test_attached_clause_entrance_guard_allows_a_complete_purpose_restart():
    words = (
        "Our mission is to analyze the logic presented in this text to try and "
        "understand how global trade is shifting."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    left = words.index("text")

    evaluation = editor._evaluate_stable_cut_boundary(left, left + 1)

    assert "dependency_phrase_entrance_split" not in evaluation["hard_issues"]
    assert evaluation["legal"], evaluation


def test_dependency_phrase_entrance_guard_allows_independent_sentence_starts():
    cases = [
        (["We", "invested.", "To", "reduce", "costs,", "we", "automated."], 1),
        (["They", "left.", "Without", "warning,", "markets", "fell."], 1),
        (["We", "stopped.", "That", "was", "enough."], 1),
    ]

    for words, cut_after in cases:
        editor = _marker_editor(words)
        editor._prepare_syntax_cut_hints()

        evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)

        assert "dependency_phrase_entrance_split" not in evaluation["hard_issues"], words
        assert evaluation["legal"], words


def test_parser_clause_chains_block_migrated_dependency_boundaries():
    cases = [
        (
            ["you", "have", "to", "ask,", "what", "exactly", "are", "you", "buying?"],
            5,
            "fronted_wh_clause_split",
            80,
        ),
        (
            ["that's", "less", "than", "a", "tenth", "the", "size", "of", "the", "model."],
            4,
            "comparative_measure_phrase_split",
            80,
        ),
        (
            (
                "But a 30% discount doesn't explain an infrastructure budget that's "
                "less than a tenth the size of your American competitors."
            ).split(),
            13,
            "comparative_measure_phrase_split",
            60,
        ),
        (
            ["They", "end", "up", "with", "an", "advanced", "model."],
            2,
            "verb_particle_preposition_chain_split",
            80,
        ),
        (
            ["spend", "less", "than", "one-tenth", "of", "what", "American", "firms", "spend."],
            5,
            "fronted_wh_clause_split",
            80,
        ),
        (
            ["The", "budget", "suddenly", "looks", "less", "like", "an", "advantage."],
            3,
            "predicate_complement_chain_split",
            560,
        ),
        (
            ["We", "wonder", "about", "the", "long", "game", "here."],
            5,
            "post_nominal_adverb_split",
            80,
        ),
        (
            ["Will", "the", "ultimate", "winner", "of", "this", "revolution", "actually", "be", "the", "country?"],
            6,
            "subject_finite_verb_split",
            520,
        ),
    ]

    for words, cut_after, issue, pause_ms in cases:
        editor = _marker_editor(words)
        additional_pause = max(0, pause_ms - 80)
        for entry in editor._active_word_entries[cut_after + 1:]:
            entry["start_time"] += additional_pause
            entry["end_time"] += additional_pause
        editor._prepare_syntax_cut_hints()

        evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)

        assert issue in evaluation["hard_issues"], (words, evaluation)
        assert not evaluation["legal"], words


def test_separable_particle_and_following_preposition_stay_in_one_predicate_chain():
    words = "The source puts Navarro's numbers up against an analysis from 2023.".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    particle = words.index("up")

    evaluation = editor._evaluate_stable_cut_boundary(particle, particle + 1)

    assert "verb_particle_preposition_chain_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_predicate_adverb_and_following_preposition_stay_in_one_chain():
    words = (
        "You cannot dismantle global supply chains without passing that cost "
        "directly to the public."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    adverb = words.index("directly")

    evaluation = editor._evaluate_stable_cut_boundary(adverb, adverb + 1)

    assert "verb_adverb_preposition_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_pre_id_candidate_cannot_remove_existing_strong_sentence_anchor():
    words = (
        "We really have to wonder about the long game here. "
        "Will the ultimate winner actually be the country that wins?"
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    old_items = [
        _word_item(editor, 0, 9, 1),
        _word_item(editor, 10, 17, 2),
        _word_item(editor, 18, 19, 3),
    ]
    migrated_items = [
        _word_item(editor, 0, 8, 1),
        _word_item(editor, 9, 14, 2),
        _word_item(editor, 15, 19, 3),
    ]

    gate = editor._can_apply_pre_id_repair_candidate(old_items, migrated_items)

    assert gate["accepted"] is False
    assert "strong_sentence_anchor_removed" in gate["reasons"]


def test_migrated_dependency_guards_allow_independent_sentence_boundaries():
    cases = [
        (["They", "ended", "up.", "With", "care,", "they", "continued."], 2),
        (["The", "budget", "looks.", "Less", "can", "be", "better."], 2),
        (["We", "discussed", "the", "game.", "Here", "is", "why."], 3),
        (["What", "changed?", "American", "firms", "responded."], 1),
    ]
    new_issue_codes = {
        "comparative_measure_phrase_split",
        "fronted_wh_clause_split",
        "post_nominal_adverb_split",
        "predicate_complement_chain_split",
        "verb_particle_preposition_chain_split",
    }

    for words, cut_after in cases:
        editor = _marker_editor(words)
        editor._prepare_syntax_cut_hints()

        evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)

        assert evaluation["legal"], (words, evaluation)
        assert not new_issue_codes.intersection(evaluation["hard_issues"]), words


def test_short_display_merge_keeps_original_when_no_safe_boundary_exists():
    words = ["Yeah,", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]
    editor = _marker_editor(words, max_words=4)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 7, 2)]

    with patch.object(editor, "_should_merge_short_display_item", return_value=True), patch.object(
        editor, "_balanced_two_item_split", return_value=[]
    ), patch.object(editor, "_safe_direct_short_item_merge", return_value=None):
        merged = editor._merge_short_display_segments(items)

    assert [item.original for item in merged] == [item.original for item in items]
    assert editor._pre_id_boundary_repairs[-1]["repair_reason"] == "short_display_merge_no_legal_boundary"


def test_final_pre_id_preserves_word_order_coverage_and_timestamps():
    words = [
        "This",
        "became",
        "a",
        "highly",
        "valuable",
        "business",
        "for",
        "the",
        "market",
        "leaders.",
    ]
    editor = _marker_editor(words, max_words=8)
    before_times = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]
    items = [_word_item(editor, 0, 3, 1), _word_item(editor, 4, 9, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == before_times
    assert repaired[0].subtitle_id is None


def test_boundary_snapshot_payload_records_pre_id_repairs():
    editor = _marker_editor(["founder", "of", "a", "non-profit"])
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 3, 2)]

    editor._validate_and_repair_final_pre_id_boundaries(items)
    payload = editor._boundary_snapshot_payload()

    assert "pre_id_boundary_repairs" in payload
    assert payload["pre_id_boundary_repairs"]


def test_subject_finite_verb_we_tend_is_hard_boundary():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"])
    editor._record_syntax_hard_issue_for_indices([0, 1], "subject_finite_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_subject_finite_verb_they_needed_is_hard_boundary():
    editor = _marker_editor(["they", "needed", "to", "hire", "more", "clerks"])
    editor._record_syntax_hard_issue_for_indices([0, 1], "subject_finite_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_subject_finite_verb_ai_is_upending_is_hard_boundary():
    editor = _marker_editor(["when", "AI", "is", "completely", "upending"])
    editor._record_syntax_hard_issue_for_indices([1, 2], "subject_finite_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_modifier_head_actually_good_is_hard_boundary():
    editor = _marker_editor(["actually", "good", "at", "this"])
    editor._record_syntax_hard_issue_for_indices([0, 1], "modifier_head_split")

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "modifier_head_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_relative_clause_subject_verb_you_can_is_hard_boundary():
    editor = _marker_editor(["the", "good", "you", "can", "do"])
    editor._record_syntax_hard_issue_for_indices([2, 3], "relative_clause_subject_verb_split")

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "relative_clause_subject_verb_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_pre_id_repairs_yeah_so_todd_subject_fragment():
    words = [
        "Yeah,",
        "so",
        "Todd",
        "is",
        "the",
        "founder",
        "of",
        "a",
        "non-profit",
        "and",
        "the",
        "author",
        "of",
        "a",
        "book,",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 14, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original.startswith("Yeah, so Todd is the founder")
    assert [(item.word_start, item.word_end) for item in repaired] == [(0, 8), (9, 14)]
    assert all(editor._evaluate_item_pair_for_final_boundary(left, right)["legal"] for left, right in zip(repaired, repaired[1:]))
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 14 for item in repaired)


def test_final_pre_id_repairs_pronoun_only_fragment():
    editor = _marker_editor(["We", "tend", "to", "view", "AI", "carefully."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original.startswith("We tend")
    assert all(item.original != "We" for item in repaired)


def test_final_pre_id_merges_high_confidence_fragment_into_unsplittable_19_word_sentence():
    words = [
        "Wow.", "Yeah.", "And", "the", "Small", "Business", "and",
        "Entrepreneurship", "Council", "points", "out", "that", "is",
        "the", "highest", "level", "this", "entire", "century.",
    ]
    editor = _marker_editor(words, max_words=16)
    items = [_word_item(editor, 0, 15, 1), _word_item(editor, 16, 18, 2)]
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    with patch.object(editor, "_safe_overlong_item_split", return_value=([], [])):
        repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [" ".join(words)]
    assert [(item.word_start, item.word_end) for item in repaired] == [(0, 18)]
    assert all(item.subtitle_id is None for item in repaired)
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def test_final_pre_id_does_not_allow_fragment_merge_over_19_words():
    words = [
        "Wow.", "Yeah.", "And", "the", "Small", "Business", "and",
        "Entrepreneurship", "Council", "points", "out", "that", "is",
        "the", "highest", "level", "ever", "this", "entire", "century.",
    ]
    editor = _marker_editor(words, max_words=16)
    items = [_word_item(editor, 0, 16, 1), _word_item(editor, 17, 19, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert all(ScreenSubtitleEditor._word_count(item.original) <= 16 for item in repaired)
    assert [item.original for item in repaired] != [" ".join(words)]


def test_final_pre_id_does_not_allow_structural_merge_when_safe_cut_exists():
    words = [
        "Wow.", "Yeah.", "And", "the", "Small", "Business", "and",
        "Entrepreneurship", "Council", "points", "out", "that", "is",
        "the", "highest", "level", "this", "entire", "century.",
    ]
    editor = _marker_editor(words, max_words=16)
    items = [_word_item(editor, 0, 15, 1), _word_item(editor, 16, 18, 2)]
    safe_split = [_word_item(editor, 0, 9), _word_item(editor, 10, 18)]

    with patch.object(editor, "_safe_overlong_item_split", return_value=(safe_split, [])):
        repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert all(ScreenSubtitleEditor._word_count(item.original) <= 16 for item in repaired)
    assert [item.original for item in repaired] != [" ".join(words)]


def test_final_pre_id_attaches_standalone_so_to_next_sentence():
    editor = _marker_editor(["So,", "this", "matters", "now."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 3, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original == "So, this matters now."


def test_final_pre_id_keeps_independent_short_answers():
    editor = _marker_editor(["No.", "Really?", "This", "changed."])
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 1, 2), _word_item(editor, 2, 3, 3)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired][:2] == ["No.", "Really?"]


def test_weak_fragment_repair_does_not_cross_speaker_change():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"])
    editor._active_source_segments_by_id[1].speaker = "A"
    editor._active_source_segments_by_id[2].speaker = "B"
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]


def test_weak_fragment_repair_does_not_cross_long_pause():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"])
    editor._active_word_entries[1]["start_time"] = editor._active_word_entries[0]["end_time"] + 800
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]


def test_internal_transition_attaches_to_following_sentence():
    words = [
        "having",
        "80",
        "000",
        "Alternatively,",
        "if",
        "you",
        "want",
        "to",
        "work",
        "directly",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 9, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original == "having 80 000"
    assert repaired[1].original.startswith("Alternatively, if you want")
    assert all("Alternatively" not in item.original or item.original.startswith("Alternatively") for item in repaired)


def test_final_pre_id_repair_does_not_create_new_hard_issue():
    editor = _marker_editor(["We", "tend", "to", "view", "AI", "as", "important."])
    editor._record_syntax_hard_issue_for_indices([0, 1], "subject_finite_verb_split")
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 6, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert all(
        editor._evaluate_item_pair_for_final_boundary(left, right)["legal"]
        for left, right in zip(repaired, repaired[1:])
    )


def test_unresolved_weak_fragment_is_recorded_when_no_safe_repair():
    editor = _marker_editor(["We", "tend", "to", "view", "AI"], max_words=2)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert editor._pre_id_boundary_repairs[-1]["unresolved_hard_issue"] is True


def test_final_pre_id_second_phase_preserves_word_order_and_timestamps():
    words = ["We", "tend", "to", "view", "AI", "as", "important."]
    editor = _marker_editor(words, max_words=14)
    before_times = [(entry["start_time"], entry["end_time"]) for entry in editor._active_word_entries]
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 6, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )
    assert [(entry["start_time"], entry["end_time"]) for entry in editor._active_word_entries] == before_times
    assert all(item.subtitle_id is None for item in repaired)


def test_boundary_snapshots_record_stage_changes_before_subtitle_ids():
    editor = _marker_editor(["I", "mean,", "this", "market", "changed."])
    items = [
        ScreenSubtitleItem([1], "I mean,", "", word_start=0, word_end=1),
        ScreenSubtitleItem([1], "this market changed.", "", word_start=2, word_end=4),
    ]
    editor._capture_boundary_snapshot(
        "_stable_cut_items",
        items,
        changed_by="_stable_cut_items",
        previous_items=None,
    )
    merged = editor._merge_standalone_discourse_markers(items)
    editor._capture_boundary_snapshot(
        "_merge_standalone_discourse_markers",
        merged,
        changed_by="_merge_standalone_discourse_markers",
        previous_items=editor._boundary_snapshot_items("_stable_cut_items"),
    )

    payload = editor._boundary_snapshot_payload()

    assert [stage["stage"] for stage in payload["stages"]] == [
        "_stable_cut_items",
        "_merge_standalone_discourse_markers",
    ]
    assert payload["changes"][0]["change_type"] == "initial_dp_boundaries"
    assert any(
        change["created_or_modified_by"] == "_merge_standalone_discourse_markers"
        for change in payload["changes"][1]["changes"]
    )
    assert all(item.subtitle_id is None for item in merged)
    assert isinstance(payload["stages"][0]["boundaries"][0]["pause_ms"], int)
    assert "boundary_score" in payload["stages"][0]["boundaries"][0]


def test_final_stable_english_boundaries_do_not_change_for_video_layout():
    editor = _marker_editor(
        [
            "This", "is", "a", "deliberately", "long", "but", "grammatical",
            "English", "subtitle", "sentence", "that", "should", "stay", "frozen.",
        ]
    )

    items = editor._finalize_stable_english_boundaries([])

    assert " ".join(item.original for item in items) == (
        "This is a deliberately long but grammatical English subtitle sentence that should stay frozen."
    )
    assert all(item.subtitle_id is None for item in items)
    assert [stage["stage"] for stage in editor._boundary_snapshots] == [
        "_stable_cut_items",
        "_merge_standalone_discourse_markers",
        "_merge_short_display_segments",
        "_rebalance_edge_discourse_markers",
        "_validate_and_repair_final_pre_id_boundaries",
    ]


def test_final_gate_blocks_particle_preposition_complement_split():
    editor = _marker_editor(["straight", "into", "the", "absolute", "tundra"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "particle_or_preposition_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_keeps_preposition_object_boundary_illegal_after_long_pause():
    editor = _marker_editor(["optimism", "about", "finding", "a", "good", "job."])
    editor._active_word_entries[2]["start_time"] = editor._active_word_entries[1]["end_time"] + 500

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert evaluation["pause_ms"] == 500
    assert "preposition_object_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_stable_cut_keeps_preposition_object_phrase_together_in_long_sentence():
    text = (
        "I mean Gallup data shows optimism among 15 to 34 year-olds "
        "about finding a good job plummeted from 75% to just 43% recently."
    )

    parts = _split_text(text, max_words=16)

    assert all(not part.rstrip().lower().endswith("about") for part in parts)
    assert all(not part.lstrip().lower().startswith("finding") for part in parts)
    assert "about finding a good job" in " ".join(parts).lower()


def test_parser_confirmed_verb_object_boundary_stays_illegal_after_long_pause():
    editor = _marker_editor(
        ["they", "are", "setting", "up", "large", "new", "facilities."]
    )
    editor._prepare_syntax_cut_hints()
    editor._active_word_entries[4]["start_time"] = editor._active_word_entries[3]["end_time"] + 650

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)

    assert evaluation["pause_ms"] == 650
    assert "short_verb_object_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_clause_introducer_from_ending_a_cue():
    editor = _marker_editor(
        [
            "the", "question", "has", "to", "do", "with", "how", "these",
            "systems", "are", "funded.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(6, 7)

    assert "clause_introducer_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_verb_from_its_preposition_complement():
    editor = _marker_editor(
        ["investors", "got", "liquidated", "in", "that", "doom", "loop."]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "verb_preposition_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_parser_blocks_verb_from_numeric_result_expression():
    editor = _marker_editor(
        [
            "the", "stock", "kept", "crashing", "52%", "from", "its",
            "June", "peak.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    verb_to_result = editor._evaluate_stable_cut_boundary(3, 4)
    result_to_qualifier = editor._evaluate_stable_cut_boundary(4, 5)

    assert "verb_numeric_result_split" in verb_to_result["hard_issues"]
    assert "numeric_result_qualifier_split" in editor._syntax_hard_cut_issues[(4, 5)]
    assert not verb_to_result["legal"]
    assert not result_to_qualifier["legal"]


def test_numeric_result_guard_stops_before_coordinated_clause():
    editor = _marker_editor(
        [
            "China's", "GDP", "is", "two-thirds", "the", "size", "of",
            "America's,", "and", "actually", "a", "third", "bigger", "when",
            "you", "adjust", "for", "purchasing", "power.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    boundary = editor._evaluate_stable_cut_boundary(7, 8)

    assert boundary["legal"] is True
    assert "verb_numeric_result_split" not in boundary["hard_issues"]


def test_parser_mapping_keeps_numeric_result_after_hyphenated_ledger_word():
    editor = _marker_editor(
        [
            "even", "a", "six-fold", "profit", "jump", "wasn't", "enough",
            "to", "stop", "the", "stock", "from", "crashing", "52%",
            "from", "its", "June", "peak.",
        ]
    )
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(12, 13)

    assert "verb_numeric_result_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_stable_cut_balances_the_full_sentence_instead_of_leaving_a_short_tail():
    words = [
        "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
        "india", "juliet", "kilo", "lima", "mike", "november", "oscar",
        "papa", "quebec", "romeo", "sierra", "tango.",
    ]
    editor = _marker_editor(words, max_words=16)

    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))

    assert [end - start + 1 for start, end in ranges] == [10, 10]


def test_stable_cut_does_not_evaluate_overflow_when_normal_partition_exists():
    words = [
        "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
        "india", "juliet", "kilo", "lima", "mike", "november", "oscar",
        "papa", "quebec", "romeo", "sierra", "tango.",
    ]
    editor = _marker_editor(words, max_words=16)
    overflow_checks = []

    def record_overflow_check(start, end):
        overflow_checks.append((start, end))
        return True

    editor._is_complete_pre_id_structural_overflow_range = record_overflow_check

    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))

    assert [end - start + 1 for start, end in ranges] == [10, 10]
    assert overflow_checks == []


def test_final_fragment_blocks_short_open_prefix_but_allows_finite_clause():
    words = "Because in America, you have dozens of competing firms today.".split()
    editor = _marker_editor(words, max_words=16)
    prefix = _word_item(editor, 0, 2, 1)
    continuation = _word_item(editor, 3, len(words) - 1, 1)

    fragment = editor._evaluate_final_display_fragment(prefix, None, continuation)

    assert "short_open_prefix_fragment" in fragment["hard_fragment_issues"]

    finite_words = "Because the market had already changed, sales doubled.".split()
    finite_editor = _marker_editor(finite_words, max_words=16)
    finite_clause = _word_item(finite_editor, 0, 5, 1)
    finite_continuation = _word_item(finite_editor, 6, len(finite_words) - 1, 1)

    finite_fragment = finite_editor._evaluate_final_display_fragment(
        finite_clause,
        None,
        finite_continuation,
    )

    assert "short_open_prefix_fragment" not in finite_fragment["hard_fragment_issues"]


def test_final_pre_id_repair_keeps_short_open_prefix_with_clause_across_pause():
    words = "Exactly. And yet, a Beijing startup won the race.".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    continuation_start = 3
    for entry in editor._active_word_entries[continuation_start:]:
        entry["start_time"] += 500
        entry["end_time"] += 500
    prefix = _word_item(editor, 0, continuation_start - 1, 1)
    continuation = _word_item(editor, continuation_start, len(words) - 1, 1)

    fragment = editor._evaluate_final_display_fragment(prefix, None, continuation)
    repaired = editor._validate_and_repair_final_pre_id_boundaries(
        [prefix, continuation]
    )

    assert editor._boundary_pause_ms(prefix, continuation) == 580
    assert "short_open_prefix_fragment" in fragment["hard_fragment_issues"]
    assert " ".join(item.original for item in repaired) == (
        "Exactly. And yet, a Beijing startup won the race."
    )
    assert all(not item.original.endswith("And yet,") for item in repaired)
    assert all(not item.original.endswith("a Beijing") for item in repaired)
    assert any(
        "And yet, a Beijing startup won the race." in item.original
        for item in repaired
    )


def test_orphaned_predicate_parse_is_cached_for_the_same_frozen_span():
    editor = _marker_editor("they spend less today.".split(), max_words=16)
    predicate = _word_item(editor, 1, 3, 1)
    parse_calls = []

    class Root:
        dep_ = "ROOT"
        pos_ = "VERB"
        tag_ = "VBP"
        children = ()

    def parse(text):
        parse_calls.append(text)
        return [Root()]

    editor._load_syntax_nlp = lambda: parse

    first = editor._orphaned_finite_predicate_issues(predicate)
    second = editor._orphaned_finite_predicate_issues(predicate)

    assert first == ["right_orphaned_finite_predicate"]
    assert second == first
    assert parse_calls == ["spend less today."]


def test_orphaned_predicate_detects_a_leading_passive_before_a_complete_clause():
    text = "was financed by a Chinese bank, so now the entire cake is illegal."
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    item = _word_item(editor, 0, len(words) - 1, 1)

    assert editor._orphaned_finite_predicate_issues(item) == [
        "right_orphaned_finite_predicate"
    ]


def test_orphaned_predicate_keeps_questions_conditionals_and_nonfinite_intros():
    cases = [
        "Was the policy successful?",
        "Had investors expected this, markets would have reacted.",
        "Walking home, she called.",
    ]
    for text in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        item = _word_item(editor, 0, len(words) - 1, 1)

        assert editor._orphaned_finite_predicate_issues(item) == [], text


def test_final_gate_soft_flags_heuristic_short_verb_object_split():
    editor = _marker_editor(["issued", "this", "stark", "public", "warning"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "short_verb_object_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_blocks_auxiliary_predicate_split():
    editor = _marker_editor(["work", "doesn't", "have", "to", "be", "a", "tradeoff"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "auxiliary_predicate_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_soft_flags_heuristic_catenative_verb_complement_split():
    editor = _marker_editor(["helped", "expose", "the", "crimes"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "verb_complement_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_blocks_numeric_unit_or_noun_split():
    editor = _marker_editor(["80", "000", "hours"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "numeric_unit_or_noun_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_numeric_sentence_restart_after_long_pause_is_legal():
    for left, restart in (("700", "By"), ("570", "Which")):
        editor = _marker_editor([left, "000", restart, "2025"])
        editor._active_word_entries[1]["end_time"] = 1000
        editor._active_word_entries[2]["start_time"] = 1500

        evaluation = editor._evaluate_stable_cut_boundary(1, 2)

        assert evaluation["legal"]
        assert "numeric_unit_or_noun_split" not in evaluation["hard_issues"]


def test_punctuated_numeric_model_allows_a_determiner_clause_restart():
    editor = _marker_editor(
        [
            "less",
            "powerful",
            "than",
            "an",
            "H",
            "100,",
            "the",
            "cloud",
            "giants",
            "argue",
        ]
    )
    editor._active_word_entries[5]["end_time"] = 1000
    editor._active_word_entries[6]["start_time"] = 1746

    evaluation = editor._evaluate_stable_cut_boundary(5, 6)

    assert evaluation["legal"]
    assert "numeric_unit_or_noun_split" not in evaluation["hard_issues"]


def test_punctuated_year_allows_a_determiner_clause_restart_without_long_pause():
    editor = _marker_editor(
        ["at", "the", "end", "of", "2025,", "this", "adjusted", "number"]
    )
    editor._active_word_entries[4]["end_time"] = 1000
    editor._active_word_entries[5]["start_time"] = 1340

    evaluation = editor._evaluate_stable_cut_boundary(4, 5)

    assert evaluation["legal"]
    assert "numeric_unit_or_noun_split" not in evaluation["hard_issues"]


def test_numeric_unit_split_remains_hard_with_ordinary_pause():
    editor = _marker_editor(["80", "000", "hours"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "numeric_unit_or_noun_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_numeric_sentence_boundary_is_not_repaired_as_a_numeric_phrase():
    editor = _marker_editor(["2019.", "Right."])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert evaluation["legal"]
    assert "numeric_unit_or_noun_split" not in evaluation["hard_issues"]


def test_final_gate_soft_flags_heuristic_compound_noun_split():
    editor = _marker_editor(["large-scale", "job", "displacement"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "compound_noun_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_soft_flags_heuristic_modifier_noun_head_split():
    editor = _marker_editor(["the", "vast", "majority", "of", "people"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "modifier_noun_head_split" in evaluation["soft_issues"]
    assert evaluation["legal"]


def test_final_gate_blocks_negation_emphasis_split():
    editor = _marker_editor(["never,", "ever", "be", "automated"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "negation_or_emphasis_fragment" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_stranded_leading_of_complement():
    editor = _marker_editor(["the", "mechanics", "of", "resilience"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "stranded_leading_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_stranded_leading_with_complement():
    editor = _marker_editor(["was", "met", "with", "hostility"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "stranded_leading_complement_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_time_range_to_continuation():
    editor = _marker_editor(["working", "9", "a", "m.", "to", "9", "p", "m."])

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)

    assert "time_range_continuation_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_coordinated_modifier_split():
    editor = _marker_editor(["a", "massive", "economic", "and", "social", "pressure", "cooker"])

    evaluation = editor._evaluate_stable_cut_boundary(2, 3)

    assert "coordinated_modifier_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_modifier_chain_split():
    editor = _marker_editor(["a", "massive", "economic", "and", "social", "pressure", "cooker"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "modifier_chain_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_final_gate_blocks_high_confidence_phrasal_verb_particle_split():
    editor = _marker_editor(["we", "really", "have", "to", "look", "at", "the", "mechanics"])

    evaluation = editor._evaluate_stable_cut_boundary(4, 5)

    assert "protected_phrasal_boundary_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_number_anchor_accepts_billion_to_chinese_yi_conversion():
    editor = _id_editor()
    anchors = editor._build_group_allocation_anchors("They raised 57.9 billion yuan.")

    number_anchor = next(anchor for anchor in anchors if anchor["type"] == "number")

    assert number_anchor["value"] == "57900000000"
    assert editor._allocation_anchor_present(number_anchor["value"], "number", "他们募集了579亿人民币。")
    assert editor._allocation_anchor_present("8600000000", "number", "大约是86亿美元。")


def test_number_anchor_accepts_decade_and_century_chinese_equivalents():
    editor = _id_editor()

    assert editor._allocation_anchor_present("2000", "number", "他在21世纪初转向健美。")
    assert editor._allocation_anchor_present("1800", "number", "可以想象成19世纪铺设铁路。")


def test_negation_anchor_accepts_natural_chinese_question_tags_and_until_pattern():
    editor = _id_editor()

    assert editor._allocation_anchor_present("negation", "negation", "对吧？")
    assert editor._allocation_anchor_present("negation", "negation", "他直到62岁才创办那家公司。")


def test_legacy_sample_specific_fragment_rules_are_not_hardcoded():
    assert not ScreenSubtitleEditor._is_bad_chinese_fragment("而如果联系更宏观层面，")
    assert not ScreenSubtitleEditor._is_bad_chinese_fragment("经过一栋空置的政府大楼")


def test_final_fragment_gate_repairs_trailing_dependent_fragments():
    editor = _marker_editor(["It's", "a", "mind-bending", "number.", "And", "they", "aren't", "funding"], max_words=8)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 4, 2), _word_item(editor, 5, 7, 3)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    texts = [item.original for item in repaired]
    assert texts == ["It's a mind-bending number. And they aren't funding"]
    assert all(not editor._ends_with_dependent_boundary_token(text) for text in texts)
    assert all(item.subtitle_id is None for item in repaired)


def test_final_fragment_gate_repairs_possessive_and_quantifier_tails():
    editor = _marker_editor(
        ["all", "the", "capital", "committed", "to", "markets", "company's", "trajectory"],
        max_words=6,
    )
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 5, 2), _word_item(editor, 6, 6, 3), _word_item(editor, 7, 7, 4)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    texts = [item.original for item in repaired]
    assert texts == ["all the capital committed to markets", "company's trajectory"]
    assert all(item.subtitle_id is None for item in repaired)


def test_final_gate_allows_sentence_initial_to_me_after_punctuation():
    editor = _marker_editor(["brutal.", "To", "me", "that", "is", "clear"])

    evaluation = editor._evaluate_stable_cut_boundary(0, 1)

    assert "stranded_leading_complement_split" not in evaluation["hard_issues"]


def test_pre_id_repair_keeps_degree_modifier_and_infinitive_complement_together():
    words = (
        "They paused the experiments to prioritize safety, standardization, "
        "and, well, most likely, to manage the blowback from traditional "
        "taxi drivers whose livelihoods were immediately threatened."
    ).split()
    editor = _marker_editor(words, max_words=16)
    likely_index = words.index("likely,")
    well_index = words.index("well,")
    for entry in editor._active_word_entries[well_index:]:
        entry["start_time"] += 440
        entry["end_time"] += 440
    for entry in editor._active_word_entries[likely_index + 1 :]:
        entry["start_time"] += 540
        entry["end_time"] += 540
    editor._prepare_syntax_cut_hints()
    items = [
        _word_item(editor, 0, likely_index, 1),
        _word_item(editor, likely_index + 1, len(words) - 1, 2),
    ]

    old_boundary_evaluation = editor._evaluate_item_pair_for_final_boundary(
        items[0],
        items[1],
    )
    assert "modified_infinitive_scope_split" in old_boundary_evaluation["hard_issues"]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [
        "They paused the experiments to prioritize safety, standardization, and, well,",
        "most likely, to manage the blowback from traditional taxi drivers whose livelihoods were immediately threatened.",
    ]
    assert all(
        editor._evaluate_item_pair_for_final_boundary(left, right)["legal"]
        for left, right in zip(repaired, repaired[1:])
    )
    assert editor._pre_id_boundary_repairs[-1]["old_cut_word_index"] == [
        likely_index,
        likely_index + 1,
    ]


def test_degree_modifier_fallback_blocks_most_likely_split_without_parser():
    editor = _marker_editor(["well,", "most", "likely,", "to", "manage"])

    evaluation = editor._evaluate_stable_cut_boundary(1, 2)

    assert "adverb_adjective_split" in evaluation["hard_issues"]
    assert not evaluation["legal"]


def test_modified_infinitive_scope_rule_does_not_block_ordinary_purpose_clause():
    words = "They paused the experiments, to manage the blowback.".split()
    editor = _marker_editor(words)
    to_index = words.index("to")
    for entry in editor._active_word_entries[to_index:]:
        entry["start_time"] += 540
        entry["end_time"] += 540
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(to_index - 1, to_index)

    assert "modified_infinitive_scope_split" not in evaluation["hard_issues"]
    assert evaluation["legal"]


def test_final_fragment_gate_repairs_incomplete_interrogative_fragment():
    editor = _marker_editor(["How", "on", "earth", "do", "you", "know", "this?"], max_words=14)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 6, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert repaired[0].original.startswith("How on earth do")
    assert all(item.subtitle_id is None for item in repaired)


def test_final_repair_does_not_create_adjacent_subject_fragment():
    editor = _marker_editor(["what", "you", "are", "actually", "good", "at"], max_words=14)
    items = [_word_item(editor, 0, 1, 1), _word_item(editor, 2, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert all(
        editor._evaluate_item_pair_for_final_boundary(
            left,
            right,
            repaired[index - 1] if index > 0 else None,
        )["legal"]
        for index, (left, right) in enumerate(zip(repaired, repaired[1:]))
    )


def test_final_repair_does_not_create_ordinary_one_word_fragment():
    editor = _marker_editor(["a", "Pulitzer", "Prize-winning", "journalist", "reported", "it"], max_words=5)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert not any(editor._is_ordinary_one_word_fragment(item.original) for item in repaired)
    assert all(ScreenSubtitleEditor._word_count(item.original) <= 5 for item in repaired)


def test_final_fragment_gate_repairs_connector_and_reflexive_fragments():
    words = [
        "And",
        "another",
        "Douban",
        "user",
        "made",
        "a",
        "sharp",
        "observation",
        "about",
        "the",
        "writing",
        "itself.",
    ]
    editor = _marker_editor(words, max_words=14)
    items = [
        _word_item(editor, 0, 0, 1),
        _word_item(editor, 1, 10, 2),
        _word_item(editor, 11, 11, 3),
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert " ".join(item.original for item in repaired).replace(" .", ".") == " ".join(words)
    assert not any(item.original == "And" for item in repaired)
    assert not any(item.original == "itself." for item in repaired)
    assert all(
        editor._evaluate_item_pair_for_final_boundary(
            left,
            right,
            repaired[index - 1] if index > 0 else None,
        )["legal"]
        for index, (left, right) in enumerate(zip(repaired, repaired[1:]))
    )


def test_final_fragment_gate_records_unresolved_when_no_legal_solution():
    editor = _marker_editor(["How", "on", "earth", "do", "you"], max_words=2)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 4, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [item.original for item in items]
    assert any(
        repair["unresolved_hard_issue"]
        for repair in editor._pre_id_boundary_repairs
    )


def test_podcast_template_prefers_stable_manifest_subtitle():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stale = root / "222-original-top.srt"
        stable = root / "stable-final-original-top.srt"
        manifest = root / "stable-final-manifest.json"
        ass = root / "output.ass"
        stale.write_text("stale", encoding="utf-8")
        stable.write_text("stable", encoding="utf-8")
        ass.write_text("", encoding="utf-8")
        manifest.write_text(
            json.dumps({"paths": {"original_top_srt": str(stable)}}),
            encoding="utf-8",
        )

        resolved = resolve_podcast_template_subtitle("C:/tmp/222.m4a", str(ass))

        assert Path(resolved) == stable


def test_podcast_template_blocks_failed_stable_manifest_subtitle():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stable = root / "stable-final-original-top.srt"
        manifest = root / "stable-final-manifest.json"
        ass = root / "output.ass"
        stable.write_text("stable", encoding="utf-8")
        ass.write_text("", encoding="utf-8")
        manifest.write_text(
            json.dumps(
                {
                    "render_blocked": True,
                    "paths": {"original_top_srt": str(stable)},
                }
            ),
            encoding="utf-8",
        )

        try:
            resolve_podcast_template_subtitle("C:/tmp/222.m4a", str(ass))
            assert False, "blocked manifest must stop podcast-template synthesis"
        except RuntimeError as exc:
            assert "阻止" in str(exc)


def test_podcast_template_does_not_fall_back_when_manifest_is_invalid_or_unusable():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stale = root / "222-original-top.srt"
        manifest = root / "stable-final-manifest.json"
        ass = root / "output.ass"
        stale.write_text("stale", encoding="utf-8")
        ass.write_text("", encoding="utf-8")

        for manifest_text in (
            "{not valid json",
            json.dumps({"paths": {"original_top_srt": str(root / "missing.srt")}}),
        ):
            manifest.write_text(manifest_text, encoding="utf-8")
            try:
                resolve_podcast_template_subtitle("C:/tmp/222.m4a", str(ass))
            except RuntimeError as exc:
                assert "阻止" in str(exc)
            else:
                raise AssertionError("an existing manifest must not fall back to a stale subtitle")


def test_podcast_template_reuses_legacy_reading_speed_manifest_when_revalidated():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        stable = root / "stable-final-original-top.srt"
        manifest = root / "stable-final-manifest.json"
        ass = root / "output.ass"
        stable.write_text(
            "1\n00:00:00,000 --> 00:00:01,340\n"
            "I can see why you'd think that. I mean,\n"
            "我理解你为什么这么想。我的意思是，\n",
            encoding="utf-8-sig",
        )
        ass.write_text("", encoding="utf-8")
        manifest.write_text(
            json.dumps(
                {
                    "render_blocked": True,
                    "validation_summary": {
                        "errors": [{"code": "reading_speed_error"}]
                    },
                    "paths": {"original_top_srt": str(stable)},
                }
            ),
            encoding="utf-8",
        )

        resolved = resolve_podcast_template_subtitle("C:/tmp/222.m4a", str(ass))

        assert Path(resolved) == stable


def test_podcast_template_preserves_full_media_duration_when_subtitles_end_early():
    class _FakeStdin:
        def __init__(self):
            self.frames = []

        def write(self, payload):
            self.frames.append(payload)

        def close(self):
            pass

    class _FakeProcess:
        def __init__(self):
            self.stdin = _FakeStdin()

        def wait(self):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("successful template process must not be killed")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        srt = root / "short.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:00,200\nHello.\n你好。\n",
            encoding="utf-8",
        )
        process = _FakeProcess()

        def _start_fake_process(command, *args, **kwargs):
            Path(command[-1]).write_bytes(b"fake-video")
            return process

        with patch.object(podcast_learning_video, "get_duration", return_value=3.0), \
             patch.object(podcast_learning_video, "FPS", 1), \
             patch.object(podcast_learning_video, "make_base", return_value=Image.new("RGBA", (2, 2))), \
             patch.object(podcast_learning_video, "make_avatars", return_value=(None, None)), \
             patch.object(podcast_learning_video, "draw_frame", return_value=Image.new("RGB", (2, 2))), \
             patch.object(podcast_learning_video.subprocess, "Popen", side_effect=_start_fake_process):
            podcast_learning_video.render_podcast_learning_video(
                "source.m4a",
                str(srt),
                str(root / "output.mp4"),
            )

        assert len(process.stdin.frames) == 3


def test_podcast_template_uses_frozen_task_configuration():
    config = SynthesisConfig(
        podcast_learning_template=True,
        podcast_template_style="文章单词",
        podcast_template_ai_vocab=True,
        podcast_template_english_only=True,
        podcast_template_title="Frozen title",
        podcast_template_background="C:/images/background.png",
        podcast_template_cover="C:/images/cover.png",
        podcast_template_logo="C:/images/brand-logo.png",
        podcast_template_date="Jul 31st 2026",
    )
    task = SynthesisTask(
        video_path="C:/media/input.m4a",
        subtitle_path="C:/media/input.srt",
        output_path="C:/media/output.mp4",
        synthesis_config=config,
    )
    with patch("app.thread.video_synthesis_thread.render_podcast_learning_video") as render:
        VideoSynthesisThread(task).run()

    kwargs = render.call_args.kwargs
    assert kwargs["template_style"] == "文章单词"
    assert kwargs["show_ai_vocab"] is True
    assert kwargs["english_only"] is True
    assert kwargs["title_text"] == "Frozen title"
    assert kwargs["background_path"] == "C:/images/background.png"
    assert kwargs["cover_path"] == "C:/images/cover.png"
    assert kwargs["logo_path"] == "C:/images/brand-logo.png"
    assert kwargs["date_text"] == "Jul 31st 2026"


def test_podcast_english_only_mode_hides_only_chinese_subtitle_for_both_templates():
    cue = podcast_learning_video.Cue(
        1,
        0.0,
        3.0,
        "They rely heavily on model distillation.",
        "他们非常依赖模型蒸馏。",
        "male",
    )
    plan = {
        1: {
            "key": "model distillation",
            "word": "model distillation",
            "meaning": "模型蒸馏",
            "detail": "用大模型训练更小的模型",
            "card_type": "concept",
            "display_id": "1:model distillation",
            "display_start": 0.0,
        }
    }

    base = Image.new("RGBA", (1920, 1080), (18, 30, 48, 255))
    with patch.object(podcast_learning_video, "draw_avatar"):
        standard_bilingual = podcast_learning_video.draw_frame(
            base,
            None,
            None,
            cue,
            plan,
            show_vocab=True,
            display_time=1.0,
        )
        standard_english = podcast_learning_video.draw_frame(
            base,
            None,
            None,
            cue,
            plan,
            show_vocab=True,
            display_time=1.0,
            english_only=True,
        )

    standard_diff = ImageChops.difference(
        standard_bilingual.convert("RGB"), standard_english.convert("RGB")
    )
    assert standard_diff.getbbox() is not None
    assert standard_diff.getbbox()[1] > 850
    assert (
        standard_bilingual.crop((0, 0, 1920, 850)).tobytes()
        == standard_english.crop((0, 0, 1920, 850)).tobytes()
    )

    article_image = Image.new(
        "RGB",
        (podcast_learning_video.acx(854), podcast_learning_video.acy(480)),
        (42, 96, 128),
    )
    article_bilingual = podcast_learning_video.draw_article_frame(
        article_image,
        cue,
        plan,
        show_vocab=True,
        title_text="AI Economics",
        display_time=1.0,
    )
    article_english = podcast_learning_video.draw_article_frame(
        article_image,
        cue,
        plan,
        show_vocab=True,
        title_text="AI Economics",
        display_time=1.0,
        english_only=True,
    )
    article_diff = ImageChops.difference(
        article_bilingual.convert("RGB"), article_english.convert("RGB")
    )
    assert article_diff.getbbox() is not None
    assert article_diff.getbbox()[1] > 850
    assert (
        article_bilingual.crop((0, 0, 1920, 850)).tobytes()
        == article_english.crop((0, 0, 1920, 850)).tobytes()
    )


def test_article_cover_renders_unmasked_date_and_preserves_empty_opt_out():
    dark_article = Image.new(
        "RGBA",
        (
            podcast_learning_video.acx(854),
            podcast_learning_video.acy(480),
        ),
        (18, 54, 86, 255),
    )
    light_article = Image.new("RGBA", dark_article.size, (232, 236, 228, 255))

    without_date = podcast_learning_video.decorate_article_cover(dark_article, "")
    with_dark_cover = podcast_learning_video.decorate_article_cover(
        dark_article,
        "Aug 21st 2026",
    )
    with_light_cover = podcast_learning_video.decorate_article_cover(
        light_article,
        "2026年8月21日",
    )

    assert without_date.tobytes() == dark_article.tobytes()
    dark_diff = ImageChops.difference(
        dark_article.convert("RGB"),
        with_dark_cover.convert("RGB"),
    ).getbbox()
    light_diff = ImageChops.difference(
        light_article.convert("RGB"),
        with_light_cover.convert("RGB"),
    ).getbbox()
    assert dark_diff is not None and light_diff is not None
    assert dark_diff[0] > dark_article.width // 2
    assert light_diff[0] > light_article.width // 2
    assert dark_diff[1] > 0 and light_diff[1] > 0
    assert dark_diff[2] < dark_article.width
    assert light_diff[2] < light_article.width
    assert dark_diff[3] <= podcast_learning_video.acy(72)
    assert light_diff[3] <= podcast_learning_video.acy(72)
    assert podcast_learning_video.ARTICLE_DATE_SCRIM_ENABLED is False
    assert with_dark_cover.getpixel((dark_article.width - 1, 0)) == dark_article.getpixel(
        (dark_article.width - 1, 0)
    )
    assert with_light_cover.getpixel((light_article.width - 1, 0)) == light_article.getpixel(
        (light_article.width - 1, 0)
    )


def test_article_brand_logo_is_optional_and_preserves_aspect_ratio():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        wide_path = root / "wide-logo.png"
        square_path = root / "square-logo.png"
        Image.new("RGBA", (400, 100), (30, 120, 220, 255)).save(wide_path)
        Image.new("RGBA", (200, 200), (220, 60, 80, 255)).save(square_path)

        assert podcast_learning_video.load_article_logo("") is None
        wide_logo = podcast_learning_video.load_article_logo(str(wide_path))
        square_logo = podcast_learning_video.load_article_logo(str(square_path))
        safe_width = podcast_learning_video.acx(100)
        safe_height = podcast_learning_video.acy(50)

        assert wide_logo.size == (safe_width, safe_width // 4)
        assert square_logo.size == (safe_height, safe_height)

        cover = Image.new(
            "RGBA",
            (
                podcast_learning_video.acx(854),
                podcast_learning_video.acy(480),
            ),
            (18, 54, 86, 255),
        )
        assert (
            podcast_learning_video.decorate_article_cover(cover, "", None).tobytes()
            == cover.tobytes()
        )

        transparent = Image.new("RGBA", cover.size, (0, 0, 0, 0))
        podcast_learning_video.draw_article_logo(transparent, square_logo)
        expected_left = (safe_width - safe_height) // 2
        assert transparent.getbbox() == (
            expected_left,
            0,
            expected_left + safe_height,
            safe_height,
        )


def test_article_brand_logo_rejects_missing_or_unreadable_files():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        missing = root / "missing.png"
        try:
            podcast_learning_video.load_article_logo(str(missing))
        except RuntimeError as exc:
            assert "品牌 Logo 文件不存在" in str(exc)
        else:
            raise AssertionError("missing custom Logo must block synthesis")

        invalid = root / "invalid.png"
        invalid.write_text("not an image", encoding="utf-8")
        try:
            podcast_learning_video.load_article_logo(str(invalid))
        except RuntimeError as exc:
            assert "无法读取品牌 Logo" in str(exc)
        else:
            raise AssertionError("unreadable custom Logo must block synthesis")


def test_article_opening_title_shrinks_to_keep_a_normal_long_title_in_three_lines():
    title = "如何识别人工智能写作，以及它会怎样改变我们的学习方式"
    image = Image.new("RGBA", (1920, 1080))
    draw = ImageDraw.Draw(image)

    title_font, lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        title,
        500,
        3,
        52,
        24,
        podcast_learning_video.article_source_han_serif_cn_bold_font,
        podcast_learning_video.wrap_article_title_text,
    )

    assert title_font.size >= podcast_learning_video.acx(24)
    assert "".join(lines) == title
    assert len(lines) <= 3
    assert all(
        podcast_learning_video.text_w(draw, line, title_font)
        <= podcast_learning_video.acx(500)
        for line in lines
    )


def test_article_template_uses_full_hd_canvas_and_balanced_subtitle_widths():
    article_image = Image.new(
        "RGB",
        (
            podcast_learning_video.acx(854),
            podcast_learning_video.acy(480),
        ),
    )
    cue = podcast_learning_video.Cue(
        1,
        0.0,
        2.0,
        "A compact English subtitle.",
        "这是一条应优先保持单行显示的中文字幕。",
        "male",
    )
    original_wrap_zh = podcast_learning_video.wrap_article_zh
    original_draw_zh_line = podcast_learning_video.draw_article_zh_line
    widths = []
    chinese_centers = []

    def capture_wrap_zh(draw, text, fnt, max_width):
        widths.append(max_width)
        return original_wrap_zh(draw, text, fnt, max_width)

    def capture_draw_zh_line(draw, center_x, y, text, *args, **kwargs):
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            chinese_centers.append((center_x, y))
        return original_draw_zh_line(draw, center_x, y, text, *args, **kwargs)

    with patch.object(podcast_learning_video, "wrap_article_zh", side_effect=capture_wrap_zh), \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as draw_card, \
         patch.object(podcast_learning_video, "draw_article_zh_line", side_effect=capture_draw_zh_line):
        frame = podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            vocab_plan={},
            show_vocab=True,
        )

    assert frame.size == (1920, 1080)
    assert podcast_learning_video.acx(1455) in widths
    assert not draw_card.called
    assert any(center_x == 960 for center_x, _y in chinese_centers)


def test_caption_wrapper_never_orphans_a_leading_connector_to_balance_two_lines():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "And the data certainly points to an isolationist trend."

    font = podcast_learning_video.fit_article_en_font(draw, text, 1455)
    lines = podcast_learning_video.wrap_en(draw, text, font, podcast_learning_video.acx(1455))

    assert lines[0] != "And"
    assert lines[0].startswith("And the ")
    assert all(len(line.split()) >= 3 for line in lines)


def test_caption_wrapper_preserves_preposition_and_infinitive_phrase_edges():
    chance_words = "It increases the chance of losing the thread of the sentence.".split()
    lead_words = "Okay, but how does token prediction lead to fewer commas?".split()

    assert podcast_learning_video._caption_line_break_penalty(chance_words, 4) > 0
    assert podcast_learning_video._caption_line_break_penalty(chance_words, 5) > 0
    assert podcast_learning_video._caption_line_break_penalty(chance_words, 6) < 1_000

    infinitive_start = lead_words.index("to")
    assert podcast_learning_video._caption_line_break_penalty(lead_words, infinitive_start) > 0
    assert podcast_learning_video._caption_line_break_penalty(lead_words, infinitive_start + 1) > 0


def test_caption_wrapper_distinguishes_complete_phrase_starts_from_stranded_dependencies():
    complete = "through reinforcement learning from human feedback.".split()
    complete_split = complete.index("from")
    complete_penalty = podcast_learning_video._caption_line_break_penalty(
        complete,
        complete_split,
    )
    assert 0 < complete_penalty < podcast_learning_video.CAPTION_HARD_BREAK_PENALTY

    for text, left in (
        ("according to the report", "according"),
        ("completely out of date", "completely"),
        ("far more than humans do", "more"),
    ):
        words = text.split()
        penalty = podcast_learning_video._caption_line_break_penalty(words, words.index(left) + 1)
        assert penalty >= podcast_learning_video.CAPTION_HARD_BREAK_PENALTY


def test_caption_wrapper_accepts_a_complete_article_bearing_prepositional_phrase():
    complete = (
        "Because it's basically trying to find a needle in a continent-sized "
        "haystack of information."
    ).split()
    split = complete.index("in")

    penalty = podcast_learning_video._caption_line_break_penalty(complete, split)

    assert 0 < penalty < podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    incomplete = "The value came directly from the".split()
    incomplete_split = incomplete.index("from")
    assert (
        podcast_learning_video._caption_line_break_penalty(
            incomplete,
            incomplete_split,
        )
        >= podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    )


def test_article_opening_title_wraps_on_chinese_word_boundaries():
    title = "中国年轻人为何不爱留学了？"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    title_font, lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        title,
        500,
        3,
        52,
        24,
        podcast_learning_video.article_source_han_serif_cn_bold_font,
        podcast_learning_video.wrap_article_title_text,
    )

    assert lines == ["中国年轻人为何", "不爱留学了？"]
    assert all(
        podcast_learning_video.text_w(draw, line, title_font)
        <= podcast_learning_video.acx(500)
        for line in lines
    )


def test_article_opening_title_preserves_explicit_line_breaks_and_uses_heavy_font():
    title = "中国年轻人为何\n不爱留学了？"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    title_font, lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        title,
        500,
        3,
        52,
        24,
        podcast_learning_video.article_source_han_serif_cn_bold_font,
        podcast_learning_video.wrap_article_title_text,
    )

    assert lines == ["中国年轻人为何", "不爱留学了？"]
    assert Path(title_font.path).name == "SourceHanSerifCN-Bold.otf"


def test_caption_wrapper_scales_before_breaking_a_hyphenated_compound():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    text = "Think of the AI as a stand-up comedian with no internal sense of humor."

    font = podcast_learning_video.fit_article_en_font(draw, text, 1455)
    lines = podcast_learning_video.wrap_article_en_subtitle(
        draw, text, font, podcast_learning_video.acx(1455)
    )

    assert all(not line.rstrip().endswith("stand-up") for line in lines)
    assert not podcast_learning_video._has_discouraged_caption_break(text, lines)


def test_caption_wrapper_does_not_mistake_finite_ed_verb_for_modifier():
    words = "Mikkel launched an AI-powered commercial insurance brokerage".split()
    split = words.index("an")

    assert not podcast_learning_video._looks_like_english_modifier_boundary(
        words[split - 1],
        words[split],
    )
    assert (
        podcast_learning_video._caption_line_break_penalty(words, split)
        < podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    )


def test_article_page_planner_does_not_mistake_ment_noun_for_ent_modifier():
    text = (
        "We have to look at the specific macroeconomic environment pushing workers out "
        "of traditional jobs and the shifting consumer mechanisms that are pulling them in."
    )
    cue = podcast_learning_video.Cue(
        72,
        288.773,
        296.568,
        text,
        "我们必须审视特定的宏观经济环境和不断变化的消费机制：前者把劳动者挤出传统岗位，后者又把他们拉进创业浪潮。",
        "male",
    )
    cue.subtitle_id = "S0072"
    timing_ms = [
        (288813, 288913), (288953, 289053), (289073, 289113),
        (289153, 289273), (289293, 289333), (289373, 289473),
        (289493, 290114), (290434, 291214), (291275, 291655),
        (291835, 292115), (292175, 292455), (292495, 292595),
        (292635, 292675), (292716, 293096), (293116, 293436),
        (293836, 293916), (293936, 294036), (294076, 294437),
        (294457, 294957), (294977, 295477), (295497, 295597),
        (295617, 295698), (295738, 295978), (295998, 296098),
        (296138, 296258),
    ]
    cue.word_timing = tuple(
        {
            "word_id": 825 + index,
            "surface": word,
            "start": start_ms / 1000.0,
            "end": end_ms / 1000.0,
        }
        for index, (word, (start_ms, end_ms)) in enumerate(
            zip(text.split(), timing_ms)
        )
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    assert podcast_learning_video._looks_like_english_modifier_boundary(
        "macroeconomic",
        "environment",
    )
    assert not podcast_learning_video._looks_like_english_modifier_boundary(
        "environment",
        "pushing",
    )

    plan = podcast_learning_video._build_article_english_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert " ".join(page["en"] for page in plan["pages"]) == text
    assert all(
        "macroeconomic" not in page["en"].split()[-1:]
        for page in plan["pages"][:-1]
    )
    assert any(
        "macroeconomic environment" in page["en"]
        for page in plan["pages"]
    )
    assert all(page["end"] - page["start"] >= 0.9 for page in plan["pages"])


def test_caption_wrapper_accepts_a_complete_terminal_relative_clause():
    words = "as having chemical reactions that have an activation potential.".split()
    split = words.index("that")

    penalty = podcast_learning_video._caption_line_break_penalty(words, split)

    assert 0 < penalty < podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    assert podcast_learning_video._article_page_span_is_readable(
        words[split:],
        is_first_page=False,
        paginated=True,
    )


def test_article_page_accepts_terminal_pronoun_and_phrasal_preposition():
    for words in (
        "he is the perfect test case for this.".split(),
        "toward corporate consolidation we talked about.".split(),
        "and the mechanisms are pulling them in.".split(),
    ):
        assert podcast_learning_video._article_page_span_is_readable(
            words,
            is_first_page=False,
            paginated=True,
        )


def _article_word_timing(cue):
    words = cue.en.split()
    duration = (cue.end - cue.start) / max(1, len(words))
    return tuple(
        {
            "word_id": index,
            "surface": word,
            "start": round(cue.start + index * duration, 3),
            "end": round(cue.start + (index + 1) * duration, 3),
        }
        for index, word in enumerate(words)
    )


def _attach_explicit_article_page_translations(cue, chinese_pages):
    cue.subtitle_id = cue.subtitle_id or f"S{cue.index:04d}"
    if chinese_pages is not None:
        cue.zh = "".join(chinese_pages)
    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])
    pages = [
        page
        for parent in blueprint["parents"]
        for page in parent["pages"]
    ]
    assert len(pages) == len(chinese_pages or [])
    contract = build_display_page_contract(
        blueprint["parents"],
        layout_profile=blueprint["layout_profile"],
        planner_version=blueprint["planner_version"],
        render_plans=blueprint["render_plans"],
    )
    artifact = validate_page_translation_response(
        contract,
        {
            "pages": [
                {
                    "display_page_id": page["display_page_id"],
                    "zh": chinese,
                }
                for page, chinese in zip(pages, chinese_pages or [])
            ]
        },
    )
    assert artifact["status"] == "PASS"
    assert podcast_learning_video.apply_article_display_page_translation_artifact(
        [cue],
        artifact,
    )


def test_article_template_does_not_truncate_a_long_english_subtitle():
    article_image = Image.new(
        "RGB",
        (
            podcast_learning_video.acx(854),
            podcast_learning_video.acy(480),
        ),
    )
    text = (
        "Yeah. Our report from the American Enterprise Institute details how massive "
        "corporations essentially bought out the American entrepreneurial spirit."
    )
    cue = podcast_learning_video.Cue(1, 0.0, 2.0, text, "中文译文。", "male")
    cue.word_timing = _article_word_timing(cue)
    _attach_explicit_article_page_translations(cue, ["中文", "译文。"])
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    cue.article_page_plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)
    page_count = len(cue.article_page_plan["pages"])
    en_pages = [page["en"] for page in cue.article_page_plan["pages"]]
    rendered_lines = []
    expected_lines = {
        line
        for page in en_pages
        for line in podcast_learning_video.wrap_article_en_subtitle(
            draw,
            page,
            podcast_learning_video.fit_article_en_font(draw, page, 1455),
            podcast_learning_video.acx(1455),
        )
    }
    original_draw_text = podcast_learning_video.draw_stroked_text

    def capture_draw_text(draw, xy, line, *args, **kwargs):
        if line in expected_lines:
            rendered_lines.append(line)
        return original_draw_text(draw, xy, line, *args, **kwargs)

    with patch.object(
        podcast_learning_video, "draw_stroked_text", side_effect=capture_draw_text
    ):
        for display_time in (0.5, 1.5):
            podcast_learning_video.draw_article_frame(
                article_image,
                cue,
                vocab_plan={},
                display_time=display_time,
            )

    assert page_count == 2
    assert all(4 <= len(page.split()) <= 16 for page in en_pages)
    assert " ".join(en_pages) == text
    assert set(rendered_lines) == expected_lines


def test_article_template_keeps_full_chinese_for_structural_overflow_cue():
    article_image = Image.new(
        "RGB",
        (
            podcast_learning_video.acx(854),
            podcast_learning_video.acy(480),
        ),
    )
    english = (
        "That result matters for the market. Investors are still looking for "
        "outdated clues in quarterly reports. Meanwhile, language models have "
        "quietly changed how analysts interpret demand."
    )
    chinese = (
        "这个结果对市场很重要。"
        "投资者仍在季度报告中寻找过时的线索。"
        "与此同时，语言模型已经悄然改变了分析师解读需求的方式。"
    )
    cue = podcast_learning_video.Cue(1, 0.0, 12.15, english, chinese, "male")
    cue.word_timing = _article_word_timing(cue)
    _attach_explicit_article_page_translations(
        cue,
        [
            "这个结果对市场很重要。",
            "投资者仍在季度报告中寻找过时的线索。",
            "与此同时，语言模型已经悄然改变了分析师解读需求的方式。",
        ],
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    cue.article_page_plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)
    page_count = len(cue.article_page_plan["pages"])
    zh_pages = [page["zh"] for page in cue.article_page_plan["pages"]]
    rendered_lines = []
    expected_lines = set()
    for page in zh_pages:
        zh_font = podcast_learning_video.fit_article_zh_font(
            draw,
            page,
            podcast_learning_video.acx(1455),
        )
        expected_lines.update(
            podcast_learning_video.wrap_article_zh(
                draw,
                page,
                zh_font,
                podcast_learning_video.acx(1455),
            )
        )
    original_draw_zh_line = podcast_learning_video.draw_article_zh_line

    def capture_draw_zh_line(draw, center_x, y, line, *args, **kwargs):
        if line in expected_lines:
            rendered_lines.append(line)
        return original_draw_zh_line(draw, center_x, y, line, *args, **kwargs)

    with patch.object(
        podcast_learning_video,
        "draw_article_zh_line",
        side_effect=capture_draw_zh_line,
    ):
        for page in cue.article_page_plan["pages"]:
            display_time = (page["start"] + page["end"]) / 2.0
            podcast_learning_video.draw_article_frame(
                article_image,
                cue,
                vocab_plan={},
                display_time=display_time,
            )

    assert page_count == 3
    assert all(podcast_learning_video._article_fixed_chinese_lines(draw, page) for page in zh_pages)
    assert all(not page.startswith(tuple("、，。；：！？")) for page in zh_pages)
    assert "".join(zh_pages) == chinese
    assert set(rendered_lines) == expected_lines


def test_article_visual_pages_never_split_a_chinese_lexical_unit():
    chinese = "因为这基本上就像在一片大陆那么大的信息干草堆里找一根针。"

    pages = podcast_learning_video._strict_split_chinese_visual_pages(
        chinese,
        2,
        page_word_counts=[6, 8],
        strict=True,
    )

    assert pages == [
        "因为这基本上就像在一片大陆",
        "那么大的信息干草堆里找一根针。",
    ]
    assert "".join(pages) == chinese
    assert pages[0][-1] != "大"
    assert pages[1][0] != "陆"


def test_article_visual_pages_fail_closed_when_no_safe_chinese_boundary_exists():
    with patch.object(
        podcast_learning_video,
        "_chinese_visual_token_boundaries",
        return_value=None,
    ):
        pages = podcast_learning_video._strict_split_chinese_visual_pages(
            "甲乙丙丁戊己庚辛壬癸",
            2,
            page_word_counts=[1, 1],
            strict=True,
        )

    assert pages is None


def test_article_visual_pages_use_local_token_boundaries_without_punctuation():
    pages = podcast_learning_video._strict_split_chinese_visual_pages(
        "中国AI小公司不必把有限资金砸进尖端芯片无底洞跑原始数据",
        2,
        page_word_counts=[12, 8],
        strict=True,
    )

    assert pages is not None
    assert "".join(pages) == "中国AI小公司不必把有限资金砸进尖端芯片无底洞跑原始数据"
    assert all(page for page in pages)
    assert pages[0].endswith("尖端")
    assert pages[1].startswith("芯片")


def test_article_page_timeline_uses_fixed_fonts_and_word_boundaries():
    english = (
        "Yeah. And you know what is genuinely consequential about that 1.2 "
        "million word study? Everyone still looks for outdated clues like "
        "excessive em dashes. But large language models have quietly mutated "
        "their syntax."
    )
    chinese = (
        "是的。那项120万词研究真正重要在哪里？"
        "大家仍在寻找破折号过多之类的旧线索。"
        "但大语言模型已经悄然改变了句法。"
    )
    cue = podcast_learning_video.Cue(4, 13.29, 25.44, english, chinese, "male")
    cue.word_timing = _article_word_timing(cue)
    _attach_explicit_article_page_translations(
        cue,
        [
            "是的。那项120万词研究真正重要在哪里？",
            "大家仍在寻找破折号过多之类的旧线索。",
            "但大语言模型已经悄然改变了句法。",
        ],
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)
    cue.article_page_plan = plan

    assert plan["status"] == "ok"
    assert plan["font_size"] == {
        "english": 56,
        "chinese": podcast_learning_video.ARTICLE_SUBTITLE_ZH_FONT_SIZE,
    }
    assert " ".join(page["en"] for page in plan["pages"]) == english
    assert "".join(page["zh"] for page in plan["pages"]) == chinese
    assert all(
        page["end"] - page["start"] >= 0.9
        for page in plan["pages"]
    )
    for previous, following in zip(plan["pages"], plan["pages"][1:]):
        transition = previous["end"]
        assert cue.word_timing[previous["word_end"]]["end"] <= transition
        assert transition <= cue.word_timing[following["word_start"]]["start"]
        assert podcast_learning_video.article_visual_page_index(cue, transition - 0.001) == previous["index"]
        assert podcast_learning_video.article_visual_page_index(cue, transition) == following["index"]


def test_stable_display_planner_is_deterministic_and_covers_each_word_once():
    spans = plan_word_page_spans(
        12,
        2,
        cue_start=0.0,
        cue_end=4.0,
        word_timing=tuple(
            {"start": index / 3, "end": (index + 1) / 3}
            for index in range(12)
        ),
        span_is_readable=lambda start, end, is_first, paginated: end - start >= 4,
        break_score=lambda end, target: abs(end - target),
    )

    assert spans == [(0, 6), (6, 12)]
    assert spans_cover_words(spans, 12)
    assert plan_word_page_spans(
        12,
        2,
        cue_start=0.0,
        cue_end=4.0,
        word_timing=tuple(
            {"start": index / 3, "end": (index + 1) / 3}
            for index in range(12)
        ),
        span_is_readable=lambda start, end, is_first, paginated: end - start >= 4,
        break_score=lambda end, target: abs(end - target),
    ) == spans


def test_stable_display_planner_keeps_legality_separate_from_large_soft_cost():
    diagnostics = set()
    spans = plan_word_page_spans(
        12,
        2,
        cue_start=0.0,
        cue_end=6.0,
        word_timing=tuple(
            {"start": index * 0.4, "end": index * 0.4 + 0.3}
            for index in range(12)
        ),
        span_is_readable=lambda start, end, is_first, paginated: end - start >= 4,
        break_score=lambda end, target: 15_000.0 if end == 6 else None,
        diagnostics=diagnostics,
    )

    assert spans == [(0, 6), (6, 12)]
    assert "hard_page_boundary" in diagnostics


def test_stable_display_planner_minimizes_risk_before_visual_cost():
    spans = plan_word_page_spans(
        12,
        2,
        cue_start=0.0,
        cue_end=6.0,
        word_timing=tuple(
            {"start": index * 0.4, "end": index * 0.4 + 0.3}
            for index in range(12)
        ),
        span_is_readable=lambda start, end, is_first, paginated: end - start >= 4,
        break_score=lambda end, target: {
            5: (1, -10_000.0),
            6: (0, 1_000.0),
        }.get(end),
    )

    assert spans == [(0, 6), (6, 12)]


def test_article_renderer_never_accepts_a_forbidden_line_break_in_a_long_cue():
    english = (
        "So they literally have to invent entirely new ways to solve the same math "
        "problem out of pure survival."
    )
    cue = podcast_learning_video.Cue(
        156,
        0.0,
        10.0,
        english,
        "所以，他们确实是出于纯粹的生存需求，不得不发明全新的办法来解决同一个数学问题。",
        "male",
    )
    cue.subtitle_id = "S0156"
    cue.word_timing = _article_word_timing(cue)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    blueprint = podcast_learning_video.build_article_display_page_blueprint([cue])
    english_plan = blueprint["render_plans"][0]
    assert " ".join(page["english"] for page in english_plan["pages"]) == english
    for page in english_plan["pages"]:
        assert not podcast_learning_video._has_discouraged_caption_break(
            page["english"], page["english_lines"]
        )


def test_article_renderer_keeps_short_default_cue_on_comfortable_static_profile():
    text = "A practical guide to clear reasoning beyond doubt."
    cue = podcast_learning_video.Cue(202, 5.0, 8.0, text, "一条简短的中文说明。", "male")
    cue.subtitle_id = "S0202"
    cue.word_timing = _article_word_timing(cue)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    page = plan["pages"][0]
    assert page["english_font_size"] == 56
    assert page["en_width"] == podcast_learning_video.ARTICLE_SUBTITLE_EN_COMFORTABLE_WIDTH
    assert len(page["en_lines"]) == 2
    assert " ".join(page["en_lines"]) == text
    assert page["start"] == cue.start
    assert page["end"] == cue.end


def test_article_renderer_keeps_readable_two_line_cue_on_one_static_page():
    text = "You know, this robotic vocabulary actually connects to a very human critique from way back."
    cue = podcast_learning_video.Cue(110, 335.5, 340.62, text, "其实，这种机械化的措辞，与一种相当人性化、由来已久的批评是相通的。", "male")
    cue.subtitle_id = "S0110"
    cue.word_timing = _article_word_timing(cue)
    _attach_explicit_article_page_translations(cue, None)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    assert plan["readability_warnings"] == []
    assert plan["pages"][0]["en"] == text
    assert plan["pages"][0]["zh"] == cue.zh
    assert plan["pages"][0]["start"] == cue.start
    assert plan["pages"][0]["end"] == cue.end


def test_article_fixed_layout_uses_two_word_line_only_as_a_static_fallback():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    for text in ("Stuffed with the most powerful semiconductors ever created,",):
        lines = podcast_learning_video._article_fixed_english_lines(draw, text)

        assert lines
        assert " ".join(lines) == text
        assert len(lines) == 2
        assert min(len(line.split()) for line in lines) == 2
        assert not podcast_learning_video._has_discouraged_caption_break(text, lines)


def test_article_fixed_layout_keeps_numeric_magnitude_and_following_head_together():
    text = "without requiring a 500 billion data center to run it."
    words = text.split()
    cue = podcast_learning_video.Cue(
        900,
        0.0,
        3.0,
        text,
        "而且不需要一个5000亿美元的数据中心来运行它。",
        "male",
    )
    cue.subtitle_id = "S0900"
    cue.word_timing = _article_word_timing(cue)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert plan["font_size"]["english"] == 56
    assert len(plan["pages"]) == 1
    page = plan["pages"][0]
    assert page["en"] == text
    assert 1 <= len(page["en_lines"]) <= 2
    assert " ".join(page["en_lines"]) == text
    if len(page["en_lines"]) == 2:
        boundary = (
            page["en_lines"][0].split()[-1],
            page["en_lines"][1].split()[0],
        )
        assert boundary not in {
            ("500", "billion"),
            ("billion", "data"),
            ("data", "center"),
        }
    assert all(
        podcast_learning_video._looks_like_numeric_phrase_boundary(words, split)
        for split in (4, 5, 6)
    )
    assert not podcast_learning_video._has_discouraged_caption_break(
        text,
        page["en_lines"],
    )


def test_article_page_keeps_parser_supported_tight_nonfinite_complement_together():
    cases = [
        (
            "They kept talking about the project for several important reasons today",
            "about",
        ),
        (
            "The student learns the underlying logic and patterns without needing "
            "the massive raw data processing capabilities of the teacher",
            "the",
        ),
    ]

    for text, following_word in cases:
        words = text.split()
        split = next(
            index
            for index, word in enumerate(words)
            if index > 0
            and word == following_word
            and words[index - 1].lower().endswith("ing")
        )

        def timing_with_pause(pause_ms):
            timing = []
            cursor = 0.0
            for index, word in enumerate(words):
                start = cursor
                end = start + 0.2
                timing.append(
                    {
                        "word_id": index,
                        "surface": word,
                        "start": start,
                        "end": end,
                    }
                )
                cursor = end + (pause_ms / 1000.0 if index == split - 1 else 0.04)
            return tuple(timing)

        tight_timing = timing_with_pause(40)
        relaxed_timing = timing_with_pause(400)
        tight_cue = podcast_learning_video.Cue(
            1,
            0.0,
            tight_timing[-1]["end"],
            text,
            "测试。",
            "male",
            word_timing=tight_timing,
            display_boundary_evidence={
                str(split): {
                    "soft_issues": ["verb_preposition_complement_split"],
                }
            },
        )
        relaxed_cue = podcast_learning_video.Cue(
            1,
            0.0,
            relaxed_timing[-1]["end"],
            text,
            "测试。",
            "male",
            word_timing=relaxed_timing,
            display_boundary_evidence={
                str(split): {
                    "soft_issues": ["verb_preposition_complement_split"],
                }
            },
        )

        assert podcast_learning_video._article_page_break_score(
            tight_cue,
            words,
            split,
            len(words) / 2,
            tight_timing,
        ) is None
        assert podcast_learning_video._article_page_break_score(
            relaxed_cue,
            words,
            split,
            len(words) / 2,
            relaxed_timing,
        ) is not None


def test_article_renderer_keeps_short_dangling_tail_on_one_static_page():
    text = "this sounds less like getting a discount on car parts and more like"
    cue = podcast_learning_video.Cue(
        77,
        270.722,
        274.924,
        text,
        "这不太像买汽车零件时打了折，更像是",
        "male",
    )
    cue.subtitle_id = "S0077"
    cue.word_timing = _article_word_timing(cue)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    assert plan["pages"][0]["en"] == text
    assert plan["pages"][0]["start"] == cue.start
    assert plan["pages"][0]["end"] == cue.end
    assert plan["readability_warnings"] == [
        {
            "reason": "preferred_readability_page_unscheduled",
            "requested_page_count": 2,
        }
    ]


def test_article_renderer_keeps_a_complete_phrase_on_a_static_bilingual_page():
    text = "they feed that curated, highly structured data to a new, smaller model, the student."
    chinese = "他们把经精选、高度结构化的数据喂给更小的新模型，即学生"
    cue = podcast_learning_video.Cue(64, 224.151, 230.475, text, chinese, "male")
    cue.subtitle_id = "S0064"
    cue.word_timing = _article_word_timing(cue)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    page = plan["pages"][0]
    assert page["en"] == text
    assert page["zh"] == chinese
    assert page["en_lines"] == [
        "they feed that curated, highly structured data",
        "to a new, smaller model, the student.",
    ]
    assert not podcast_learning_video._has_discouraged_caption_break(
        page["en"],
        page["en_lines"],
    )
    phrase_penalty = podcast_learning_video._caption_line_break_penalty(
        text.split(),
        text.split().index("to"),
    )
    assert 0 < phrase_penalty < podcast_learning_video.CAPTION_HARD_BREAK_PENALTY


def test_chinese_visual_page_never_starts_with_attached_punctuation():
    chinese = "然后再造一台轻量化、空气动力学极佳的四缸发动机，"

    with patch.object(
        podcast_learning_video,
        "_chinese_visual_token_boundaries",
        return_value={0, 9, len(chinese)},
    ):
        pages = podcast_learning_video._strict_split_chinese_visual_pages(
            chinese,
            2,
            page_word_counts=[5, 11],
            strict=True,
        )

    assert pages is not None
    assert "".join(pages) == chinese
    assert pages[0].endswith("、")
    assert pages[1].startswith("空气")


def test_article_renderer_keeps_modifier_head_phrase_on_one_visual_page():
    text = (
        "smaller Chinese AI firms aren't throwing their limited capital into a bottomless "
        "pit of cutting-edge chips to process raw data."
    )
    cue = podcast_learning_video.Cue(
        74,
        254.971,
        262.176,
        text,
        "中国AI小公司不必把有限资金砸进尖端芯片无底洞跑原始数据",
        "male",
    )
    cue.subtitle_id = "S0074"
    cue.word_timing = _article_word_timing(cue)
    _attach_explicit_article_page_translations(
        cue,
        [
            "中国AI小公司不必把有限资金砸进尖端芯片无底洞",
            "跑原始数据",
        ],
    )
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) >= 2
    assert " ".join(page["en"] for page in plan["pages"]) == text
    assert "".join(page["zh"] for page in plan["pages"]) == cue.zh
    assert all(len(page["en"].split()) >= 4 for page in plan["pages"])
    assert all(
        not (page["en"].endswith("bottomless") and following["en"].startswith("pit"))
        for page, following in zip(plan["pages"], plan["pages"][1:])
    )
    assert podcast_learning_video._caption_line_break_penalty(text.split(), 12) >= (
        podcast_learning_video.CAPTION_HARD_BREAK_PENALTY
    )


def test_article_renderer_uses_pixel_width_for_43_character_chinese_cue():
    chinese = "这是一段包含数字和英文缩写AI的中文文本用于测试实际像素宽度而非字符数量是否能显示即可"
    cue = podcast_learning_video.Cue(208, 8.0, 11.0, "A short cue remains on one page.", chinese, "male")
    cue.subtitle_id = "S0208"
    cue.word_timing = _article_word_timing(cue)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    assert len(chinese) == 43
    lines = podcast_learning_video._article_fixed_chinese_lines(draw, chinese)
    assert len(lines) == 2
    assert all(
        podcast_learning_video.article_subtitle_zh_text_w(
            draw,
            line,
            podcast_learning_video.article_cjk_font(
                podcast_learning_video.ARTICLE_SUBTITLE_ZH_FONT_SIZE,
                700,
            ),
        )
        <= podcast_learning_video.acx(podcast_learning_video.ARTICLE_SUBTITLE_ZH_WIDTH)
        for line in lines
    )

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    assert plan["pages"][0]["zh"] == chinese
    assert plan["pages"][0]["start"] == cue.start
    assert plan["pages"][0]["end"] == cue.end


def test_article_renderer_blocks_paginated_cue_without_verified_word_ledger():
    text = " ".join(f"word{index}" for index in range(24))
    cue = podcast_learning_video.Cue(1, 0.0, 8.0, text, "这是一段需要分页的中文字幕。" * 3, "male")
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "render_structural_overflow"
    assert plan["errors"][0]["reason"] == "missing_or_mismatched_word_ledger"


def test_article_renderer_keeps_s0188_shape_as_static_two_line_page():
    cue = podcast_learning_video.Cue(
        188,
        0.0,
        2.4,
        "through reinforcement learning from human feedback.",
        "也就是通过基于人类反馈的强化学习。",
        "male",
    )
    cue.word_timing = _article_word_timing(cue)
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))

    plan = podcast_learning_video.build_article_visual_page_plan(cue, draw)

    assert plan["status"] == "ok"
    assert len(plan["pages"]) == 1
    page = plan["pages"][0]
    assert page["en"] == cue.en
    assert page["en_lines"] == [
        "through reinforcement learning",
        "from human feedback.",
    ]
    assert page["start"] == cue.start
    assert page["end"] == cue.end


def test_article_renderer_rejects_word_ledger_text_mismatch():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subtitle_path = root / "stable-final-original-top.srt"
        subtitle_path.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nOne two.\n一二。\n",
            encoding="utf-8",
        )
        artifact_dir = root / "styled-subtitles-artifacts"
        artifact_dir.mkdir()
        timeline_path = artifact_dir / "final-cue-timeline.json"
        timeline_path.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "subtitle_id": "S0001",
                            "word_start": 0,
                            "word_end": 1,
                            "start_ms": 0,
                            "end_ms": 2000,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (artifact_dir / "word-ledger.json").write_text(
            json.dumps(
                {
                    "words": [
                        {"surface": "One", "start_ms": 0, "end_ms": 900},
                        {"surface": "three", "start_ms": 900, "end_ms": 2000},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (root / "stable-final-manifest.json").write_text(
            json.dumps({"final_cue_timeline_path": str(timeline_path)}),
            encoding="utf-8",
        )

        cues = podcast_learning_video.parse_srt(subtitle_path)

        assert not podcast_learning_video.attach_article_word_timing(cues, subtitle_path)
        assert cues[0].word_timing == ()


def test_article_renderer_blocks_before_ffmpeg_for_unplanned_fixed_font_page():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subtitle_path = root / "stable-final-original-top.srt"
        subtitle_path.write_text(
            "1\n00:00:00,000 --> 00:00:08,000\n"
            + " ".join(f"word{index}" for index in range(24))
            + "\n这是一段需要分页的中文字幕。这是一段需要分页的中文字幕。这是一段需要分页的中文字幕。\n",
            encoding="utf-8",
        )
        with patch.object(podcast_learning_video.subprocess, "Popen") as popen:
            try:
                podcast_learning_video.render_podcast_learning_video(
                    "unused-source.m4a",
                    str(subtitle_path),
                    str(root / "output.mp4"),
                    template_style="文章单词",
                )
            except podcast_learning_video.RenderStructuralOverflowError as exc:
                assert exc.code == "render_structural_overflow"
            else:
                raise AssertionError("unplanned fixed-font page must block synthesis")
        assert not popen.called


def test_article_renderer_requires_verified_word_ledger_even_for_single_page_cues():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subtitle_path = root / "stable-final-original-top.srt"
        subtitle_path.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nA short cue.\n短字幕。\n",
            encoding="utf-8",
        )
        with patch.object(podcast_learning_video.subprocess, "Popen") as popen:
            try:
                podcast_learning_video.render_podcast_learning_video(
                    "unused-source.m4a",
                    str(subtitle_path),
                    str(root / "output.mp4"),
                    template_style="文章单词",
                )
            except podcast_learning_video.RenderStructuralOverflowError as exc:
                assert exc.errors == [
                    {
                        "cue_index": "all",
                        "reason": "missing_or_mismatched_word_ledger",
                    }
                ]
            else:
                raise AssertionError("article synthesis must require a verified word ledger")
        assert not popen.called


def test_standard_chinese_subtitle_font_uses_48_then_46_before_two_lines():
    draw = ImageDraw.Draw(Image.new("RGB", (1920, 1080)))
    width = podcast_learning_video.scx(1459)

    short_font = podcast_learning_video.fit_standard_zh_font(draw, "这是一句简短的中文字幕。", width)
    reduced_font = podcast_learning_video.fit_standard_zh_font(draw, "甲" * 32, width)
    wrapped_font = podcast_learning_video.fit_standard_zh_font(draw, "甲" * 33, width)

    assert short_font.size == 48
    assert reduced_font.size == 46
    assert len(podcast_learning_video.wrap_zh(draw, "甲" * 32, reduced_font, width)) == 1
    assert wrapped_font.size == 46
    assert len(podcast_learning_video.wrap_zh(draw, "甲" * 33, wrapped_font, width)) == 2


def test_article_template_scaled_geometry_stays_on_integer_pixels():
    values = [16, 31, 68, 854, 900, 916, 1455, 1584]

    assert all(isinstance(podcast_learning_video.acx(value), int) for value in values)
    assert all(isinstance(podcast_learning_video.acy(value), int) for value in values)
    assert isinstance(podcast_learning_video.acx(16), int)
    assert isinstance(podcast_learning_video.acy(16), int)


def test_article_template_tip_font_and_wrapper_support_chinese_text():
    font = podcast_learning_video.article_mixed_font(24)
    assert Path(font.path).name.lower() == "msyh.ttc"

    draw = ImageDraw.Draw(Image.new("RGB", (800, 300)))
    lines = podcast_learning_video.wrap_article_mixed_text(
        draw,
        "playbook 不再是体育术语，常比喻一套现成的宣传策略。",
        font,
        300,
    )

    assert "".join(lines).replace(" ", "") == "playbook不再是体育术语，常比喻一套现成的宣传策略。"
    assert len(lines) >= 2
    assert not any(line in "，。！？；：、" for line in lines)


def test_article_opening_title_accent_matches_the_visible_title_height():
    image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    rect = podcast_learning_video.article_rect(916, 16, 1584, 530)
    title = "创业者的天堂"
    podcast_learning_video.draw_article_opening_topic_panel(image, rect, title)

    draw = ImageDraw.Draw(image, "RGBA")
    title_font, title_lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        title,
        500,
        3,
        52,
        24,
        podcast_learning_video.article_source_han_serif_cn_bold_font,
        podcast_learning_video.wrap_article_title_text,
    )
    line_gap = int(title_font.size * 1.25)
    block_height = max(line_gap, len(title_lines) * line_gap)
    title_x = rect[0] + podcast_learning_video.acx(92)
    first_y = (rect[1] + rect[3] - block_height) // 2
    bounds = [
        draw.textbbox((title_x, first_y + index * line_gap), line, font=title_font)
        for index, line in enumerate(title_lines)
    ]
    assert all(
        rect[0] < box[0]
        and box[2] < rect[2]
        and rect[1] < box[1]
        and box[3] < rect[3]
        for box in bounds
    )
    expected_y0 = min(box[1] for box in bounds)
    expected_y1 = max(box[3] for box in bounds)
    accent_x = rect[0] + podcast_learning_video.acx(52)
    accent_pixels = [
        y
        for y in range(rect[1], rect[3] + 1)
        if image.getpixel((accent_x, y)) == podcast_learning_video.ARTICLE_BLUE
    ]

    assert (min(accent_pixels), max(accent_pixels)) == (expected_y0, expected_y1)


def test_article_mixed_wrapper_rebalances_a_short_chinese_tail_line():
    detail = "文中指年轻人通过自主创业来摆脱僵化职场困境的途径。"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    font, lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        detail,
        500,
        2,
        26,
        20,
        lambda size: podcast_learning_video.article_cjk_font(size, 400),
        podcast_learning_video.wrap_article_mixed_text,
    )

    assert lines == [
        "文中指年轻人通过自主创业来",
        "摆脱僵化职场困境的途径。",
    ]
    assert all(
        podcast_learning_video.text_w(draw, line, font) <= podcast_learning_video.acx(500)
        for line in lines
    )


def test_article_concept_detail_wraps_after_a_semantic_lead_in():
    detail = "本句用数学隐喻说明留学回报的旧有优势已随市场变化而消失。"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    font, lines = podcast_learning_video.fit_article_wrapped_font(
        draw,
        detail,
        500,
        2,
        podcast_learning_video.ARTICLE_VOCAB_DETAIL_FONT_SIZE,
        podcast_learning_video.ARTICLE_VOCAB_DETAIL_MIN_FONT_SIZE,
        lambda size: podcast_learning_video.article_cjk_font(size, 500),
        podcast_learning_video.wrap_article_concept_detail,
    )

    assert lines == [
        "本句用数学隐喻说明",
        "留学回报的旧有优势已随市场变化而消失。",
    ]
    assert podcast_learning_video.text_w(draw, lines[1], font) > podcast_learning_video.text_w(
        draw, lines[0], font
    )
    assert all(
        podcast_learning_video.text_w(draw, line, font) <= podcast_learning_video.acx(500)
        for line in lines
    )
    assert not any("变" in line and "化" not in line for line in lines)


def test_article_concept_detail_keeps_a_short_note_on_one_line():
    detail = "指旧有优势已经消失。"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    font = podcast_learning_video.article_cjk_font(
        podcast_learning_video.ARTICLE_VOCAB_DETAIL_FONT_SIZE,
        500,
    )

    assert podcast_learning_video.wrap_article_concept_detail(
        draw,
        detail,
        font,
        podcast_learning_video.acx(500),
    ) == [detail]


def test_article_vocab_meaning_prefers_a_balanced_longer_second_line():
    meaning = "跨境监管合规制度框架与执行机制"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    font, lines = podcast_learning_video.fit_article_vocab_meaning_font(
        draw,
        meaning,
    )
    widths = [podcast_learning_video.text_w(draw, line, font) for line in lines]

    assert lines == ["跨境监管合规", "制度框架与执行机制"]
    assert "".join(lines) == meaning
    assert widths[1] >= widths[0]
    assert widths[0] / widths[1] >= (
        podcast_learning_video.ARTICLE_VOCAB_MEANING_LINE_BALANCE_RATIO
    )


def test_article_vocab_meaning_keeps_lexical_units_and_edge_particles_attached():
    meaning = "人工智能驱动的软件开发工作流与执行规范"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    font = podcast_learning_video.article_vocab_meaning_font(34)

    lines = podcast_learning_video.wrap_article_vocab_meaning(
        draw,
        meaning,
        font,
        podcast_learning_video.acx(360),
    )

    assert len(lines) == 2
    assert "".join(lines) == meaning
    assert not lines[0].endswith(tuple(podcast_learning_video.ARTICLE_VOCAB_MEANING_EDGE_PARTICLES))
    assert lines[1][0] not in podcast_learning_video.ARTICLE_VOCAB_MEANING_EDGE_PARTICLES


def test_article_vocab_meaning_fails_instead_of_truncating_a_third_line():
    meaning = "这是一个极其冗长而且完全不适合作为单词卡释义的中文说明文本" * 5
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    try:
        podcast_learning_video.fit_article_vocab_meaning_font(draw, meaning)
    except podcast_learning_video.ArticleVocabularyMeaningOverflowError as exc:
        assert "无法在两行内完整显示" in str(exc)
    else:
        raise AssertionError("an overflowing vocabulary meaning must not be truncated")


def test_article_vocab_phrase_wraps_before_becoming_tiny():
    phrase = "cross-border regulatory compliance framework"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    font, lines = podcast_learning_video.fit_article_vocab_phrase_font(draw, phrase)

    assert lines == ["cross-border regulatory", "compliance framework"]
    assert " ".join(lines) == phrase
    assert font.size >= podcast_learning_video.acx(
        podcast_learning_video.ARTICLE_VOCAB_PHRASE_MIN_FONT_SIZE
    )
    assert all(
        podcast_learning_video.text_w(draw, line, font)
        <= podcast_learning_video.acx(540)
        for line in lines
    )


def test_article_vocab_phrase_keeps_a_normal_short_phrase_on_one_line():
    phrase = "black-box algorithm"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    font, lines = podcast_learning_video.fit_article_vocab_phrase_font(draw, phrase)

    assert lines == [phrase]
    assert font.size >= podcast_learning_video.acx(
        podcast_learning_video.ARTICLE_VOCAB_PHRASE_SINGLE_LINE_MIN_FONT_SIZE
    )


def test_article_vocab_phrase_only_uses_small_fallback_for_one_unbroken_word():
    phrase = "pneumonoultramicroscopicsilicovolcanoconiosis"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    font, lines = podcast_learning_video.fit_article_vocab_phrase_font(draw, phrase)

    assert lines == [phrase]
    assert podcast_learning_video.text_w(draw, phrase, font) <= podcast_learning_video.acx(540)
    assert font.size < podcast_learning_video.acx(
        podcast_learning_video.ARTICLE_VOCAB_PHRASE_MIN_FONT_SIZE
    )


def test_article_vocab_phrase_fails_instead_of_shrinking_a_long_phrase_below_floor():
    phrase = " ".join(["institutional"] * 12)
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    try:
        podcast_learning_video.fit_article_vocab_phrase_font(draw, phrase)
    except podcast_learning_video.ArticleVocabularyPhraseOverflowError as exc:
        assert "无法在两行内清晰显示" in str(exc)
    else:
        raise AssertionError("an oversized phrase must not be rendered as tiny text")


def test_article_vocab_typography_uses_bundled_role_specific_faces():
    assert Path(podcast_learning_video.article_tip_font(24).path).name == "ChillYunmoGothicMedium.otf"
    assert Path(podcast_learning_video.article_en_font(24, 400).path).name == "ReadexPro-Regular.ttf"
    assert Path(podcast_learning_video.article_subtitle_en_font(24, 600).path).name == "RobotoSlab-SemiBold.ttf"
    assert Path(podcast_learning_video.article_vocab_phrase_font(24).path).name == "SourceSerifPro-Semibold.otf"
    assert Path(podcast_learning_video.article_source_han_serif_cn_bold_font(24).path).name == "SourceHanSerifCN-Bold.otf"
    assert Path(podcast_learning_video.article_vocab_meaning_font(24).path).name == "SourceHanSerifCN-SemiBold.otf"
    assert podcast_learning_video.ARTICLE_VOCAB_MEANING_FONT_WEIGHT == 600
    assert Path(podcast_learning_video.article_vocab_detail_font(24).path).name == "ChillYunmoGothicMedium.otf"
    assert podcast_learning_video.ARTICLE_VOCAB_DETAIL_FONT_WEIGHT == 500
    assert (
        podcast_learning_video.ARTICLE_VOCAB_DETAIL_COLOR
        == podcast_learning_video.ARTICLE_SUBTITLE_ZH_COLOR
        == (85, 103, 128, 255)
    )
    assert podcast_learning_video.ARTICLE_VOCAB_MEANING_COLOR == (42, 63, 93, 255)
    assert podcast_learning_video.ARTICLE_VOCAB_MEANING_COLOR != (
        podcast_learning_video.ARTICLE_VOCAB_DETAIL_COLOR
    )
    assert Path(podcast_learning_video.article_cjk_font(24, 400).path).name == "ChillYunmoGothicRegular.otf"
    bundled_fonts = (
        podcast_learning_video.FONT_GANTARI,
        podcast_learning_video.FONT_READEX_MEDIUM,
        podcast_learning_video.FONT_READEX_SEMIBOLD,
        podcast_learning_video.FONT_READEX_BOLD,
        podcast_learning_video.FONT_READEX_REGULAR,
        podcast_learning_video.FONT_ROBOTO_SLAB_REGULAR,
        podcast_learning_video.FONT_ROBOTO_SLAB_SEMIBOLD,
        podcast_learning_video.FONT_SOURCE_SERIF_PRO_SEMIBOLD,
        podcast_learning_video.FONT_SOURCE_HAN_SERIF_CN_BOLD,
        podcast_learning_video.FONT_SOURCE_HAN_SERIF_CN_SEMIBOLD,
        podcast_learning_video.FONT_HANCHAN_BOLD,
        podcast_learning_video.FONT_HANCHAN_HEAVY,
        podcast_learning_video.FONT_HANCHAN_MEDIUM,
        podcast_learning_video.FONT_HANCHAN_REGULAR,
    )
    assert all(path.parent == podcast_learning_video.TEMPLATE_FONT_DIR for path in bundled_fonts)
    assert all(path.exists() for path in bundled_fonts)
    assert not list(podcast_learning_video.TEMPLATE_DIR.glob("*.ttf"))
    assert not list(podcast_learning_video.TEMPLATE_DIR.glob("*.otf"))
    assert not list(podcast_learning_video.ARTICLE_TEMPLATE_DIR.glob("*.ttf"))
    assert not list(podcast_learning_video.ARTICLE_TEMPLATE_DIR.glob("*.otf"))


def test_article_vocab_detail_uses_roboto_slab_for_embedded_english():
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    size, lines = podcast_learning_video.fit_article_vocab_detail_mixed_font(
        draw,
        "企业通过 AI agent 自动处理重复任务。",
        max_width=500,
        max_lines=2,
        max_size=28,
        min_size=22,
        prefer_semantic_break=True,
    )

    tokens = [token for line in lines for token in line]
    assert "AI" in tokens
    assert "agent" in tokens
    assert Path(
        podcast_learning_video.article_vocab_detail_mixed_font("AI", size).path
    ).name == "RobotoSlab-Regular.ttf"
    assert Path(
        podcast_learning_video.article_vocab_detail_mixed_font("企业", size).path
    ).name == "ChillYunmoGothicMedium.otf"
    assert all(
        podcast_learning_video.article_vocab_detail_mixed_width(draw, line, size)
        <= podcast_learning_video.acx(500)
        for line in lines
    )


def test_article_subtitle_line_height_is_slightly_looser_than_previous_default():
    font = podcast_learning_video.article_subtitle_en_font(56, 600)
    assert podcast_learning_video.ARTICLE_SUBTITLE_EN_LINE_HEIGHT_MULTIPLIER == 1.22
    assert int(font.size * podcast_learning_video.ARTICLE_SUBTITLE_EN_LINE_HEIGHT_MULTIPLIER) > int(font.size * 1.16)


def test_vocab_highlight_keeps_attached_punctuation_but_not_whitespace():
    line = 'seriously entertain the accusation, "then reconsider it"'
    key = "seriously entertain the accusation"
    end = podcast_learning_video.extend_highlight_to_trailing_punctuation(
        line,
        line.lower().index(key) + len(key),
    )

    assert line[:end] == "seriously entertain the accusation,"
    assert line[end] == " "


def test_standard_subtitle_highlight_colors_attached_punctuation():
    line = "seriously entertain the accusation, before dismissing it"
    key = "seriously entertain the accusation"
    image = Image.new("RGBA", (1920, 1080))
    draw = ImageDraw.Draw(image)
    blue = podcast_learning_video.with_alpha(podcast_learning_video.BLUE, 255)

    with patch.object(podcast_learning_video, "draw_subtitle_shadowed_text") as draw_text:
        podcast_learning_video.draw_highlighted_line(
            image,
            draw,
            960,
            620,
            line,
            key,
            podcast_learning_video.font(podcast_learning_video.FONT_GANTARI, 32, 600),
        )

    highlighted_text = [
        call.args[3]
        for call in draw_text.call_args_list
        if call.args[5] == blue
    ]
    assert highlighted_text == ["seriously entertain the accusation,"]


def test_article_subtitle_highlight_colors_attached_punctuation():
    line = "seriously entertain the accusation,) before dismissing it"
    key = "seriously entertain the accusation"
    fill = (42, 63, 93, 255)
    highlight_fill = (47, 111, 237, 255)
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))

    with patch.object(podcast_learning_video, "draw_stroked_text") as draw_text:
        podcast_learning_video.draw_highlighted_article_line(
            draw,
            960,
            620,
            line,
            key,
            podcast_learning_video.article_en_font(40, 600),
            fill,
            highlight_fill,
        )

    highlighted_text = [
        call.args[2]
        for call in draw_text.call_args_list
        if call.args[4] == highlight_fill
    ]
    assert highlighted_text == ["seriously entertain the accusation,)"]


def test_article_subtitle_highlight_does_not_add_an_underline_for_the_matched_phrase():
    line = "Well, the government wound down those subsidies years ago."
    key = "wound down"
    fill = (42, 63, 93, 255)
    highlight_fill = (47, 111, 237, 255)
    image = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    font = podcast_learning_video.article_en_font(48, 600)
    center_x, text_y = 960, 620

    podcast_learning_video.draw_highlighted_article_line(
        draw,
        center_x,
        text_y,
        line,
        key,
        font,
        fill,
        highlight_fill,
    )

    prefix = line[:line.lower().index(key)]
    total_width = podcast_learning_video.text_w(draw, line, font)
    highlighted_x = center_x - total_width // 2 + podcast_learning_video.text_w(draw, prefix, font)
    box = draw.textbbox((highlighted_x, text_y), key, font=font)
    underline_y = box[3] + podcast_learning_video.acy(6) + podcast_learning_video.acy(2)
    underline_x = (box[0] + box[2]) // 2

    assert image.getpixel((underline_x, underline_y)) == (0, 0, 0, 0)


def test_vocab_highlight_ranges_cover_a_phrase_split_between_subtitle_lines():
    lines = [
        "Well, the government wound",
        "down those subsidies years ago.",
    ]

    assert podcast_learning_video.highlight_ranges_for_lines(lines, "wound down") == [
        (21, 26),
        (0, 4),
    ]


def test_article_subtitle_keeps_the_active_phrase_on_one_line_when_possible():
    text = "Well, the government wound down those subsidies years ago."
    key = "wound down"
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    font = podcast_learning_video.fit_article_en_font(draw, text, 1455)

    lines = podcast_learning_video.wrap_en_preserving_highlight(
        draw,
        text,
        font,
        podcast_learning_video.acx(1455),
        key,
    )

    assert " ".join(lines) == text
    assert any(key in line for line in lines)
    assert all(len(line.split()) >= 3 for line in lines)


def test_vocab_card_plan_keeps_the_latest_full_card_until_replacement():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 1.0, "A regulatory change.", "", "male"),
        podcast_learning_video.Cue(2, 1.5, 2.5, "A crackdown begins.", "", "male"),
        podcast_learning_video.Cue(3, 5.0, 6.0, "New compliance rules.", "", "male"),
        podcast_learning_video.Cue(4, 10.0, 16.0, "A quiet transition.", "", "male"),
        podcast_learning_video.Cue(5, 20.0, 21.0, "Algorithmic oversight.", "", "male"),
        podcast_learning_video.Cue(6, 25.0, 26.0, "More regulatory rules.", "", "male"),
    ]
    candidates = {
        1: {"key": "regulatory", "word": "Regulatory"},
        2: {"key": "crackdown", "word": "Crackdown"},
        3: {"key": "compliance", "word": "Compliance"},
        5: {"key": "algorithmic", "word": "Algorithmic"},
        6: {"key": "regulatory", "word": "Regulatory"},
    }

    plan = podcast_learning_video.schedule_vocab_card_plan(candidates, cues)

    assert list(plan) == [1, 5]
    assert podcast_learning_video.active_vocab_card(plan, cues[0], 0.5)["key"] == "regulatory"
    assert podcast_learning_video.vocab_card_display_state(plan, cues[2], 5.0)[1] == "full"
    assert podcast_learning_video.vocab_card_display_state(plan, cues[3], 13.0) == (plan[1], "full")
    assert podcast_learning_video.vocab_card_display_state(plan, cues[4], 20.0) == (plan[5], "full")
    assert podcast_learning_video.vocab_card_display_state(plan, None, 50.0) == (plan[5], "full")


def test_article_vocab_card_uses_only_expression_gloss_and_concept_note():
    image = Image.new(
        "RGBA",
        (podcast_learning_video.ARTICLE_WIDTH, podcast_learning_video.ARTICLE_HEIGHT),
        (255, 255, 255, 255),
    )
    item = {
        "word": "black-box algorithm",
        "phonetic": "/ˈreɡ.jə.lə.tɔːr.i/",
        "level": "TOEFL",
        "pos": "adj.",
        "meaning": "黑箱算法",
        "definition": "Related to official rules or controls.",
        "tip_en": "Often used before policy or approval.",
        "tip_zh": "常放在 policy 等名词前。",
        "card_type": "concept",
        "detail": "能给出结论，却无法说明判断过程。",
    }
    original_meaning_font = podcast_learning_video.article_vocab_meaning_font
    original_detail_font = podcast_learning_video.article_vocab_detail_font
    observed_meaning_sizes = []
    observed_detail_sizes = []

    def record_meaning_font(size):
        observed_meaning_sizes.append(size)
        return original_meaning_font(size)

    def record_detail_font(size):
        observed_detail_sizes.append(size)
        return original_detail_font(size)

    with patch.object(
        podcast_learning_video,
        "article_vocab_detail_font",
        side_effect=record_detail_font,
    ), patch.object(
        podcast_learning_video,
        "article_vocab_meaning_font",
        side_effect=record_meaning_font,
    ), patch.object(podcast_learning_video, "draw_stroked_text") as draw_text:
        podcast_learning_video.draw_article_vocab_card(
            image,
            item,
            podcast_learning_video.article_rect(916, 16, 1584, 530),
        )

    labels = [call.args[2] for call in draw_text.call_args_list]
    rendered_text = "".join(labels)
    assert "black-box algorithm" in labels
    assert "黑箱算法" in rendered_text
    assert "能给出结论，却无法说明判断过程。" in rendered_text
    assert "adj." not in rendered_text
    assert "TOEFL" not in rendered_text
    assert "IN CONTEXT" not in rendered_text
    assert "Related to official rules or controls." not in rendered_text
    assert 34 in observed_meaning_sizes
    assert podcast_learning_video.ARTICLE_VOCAB_DETAIL_FONT_SIZE in observed_detail_sizes
    meaning_calls = [
        call
        for call in draw_text.call_args_list
        if call.args[2] == "黑箱算法"
    ]
    assert meaning_calls
    assert all(
        call.args[4] == podcast_learning_video.ARTICLE_VOCAB_MEANING_COLOR
        for call in meaning_calls
    )
    detail_calls = [
        call
        for call in draw_text.call_args_list
        if "能给出结论" in call.args[2]
    ]
    assert detail_calls
    assert all(
        call.args[4] == podcast_learning_video.ARTICLE_VOCAB_DETAIL_COLOR
        for call in detail_calls
    )


def test_vocab_prompt_requests_expression_card_fields_without_dictionary_metadata():
    group = podcast_learning_video.VocabSemanticGroup(
        "VG0001",
        (1,),
        0.0,
        2.0,
        "A hallmark of quality is consistency.",
    )

    prompt = podcast_learning_video.build_vocab_selection_prompt([group], 1)

    assert "phrase" in prompt
    assert "card_type" in prompt
    assert "detail" in prompt
    assert "音标" in prompt
    assert "词性" in prompt
    assert "tip_zh" not in prompt
    assert "语义组" in prompt


def test_vocab_plan_preserves_the_exact_phrase_from_its_subtitle():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "Long hours can take a toll on health.", "长时间工作会损害健康。", "male"),
    ]
    groups = podcast_learning_video.build_vocab_semantic_groups(cues)

    plan = podcast_learning_video.normalize_vocab_plan(
        [{
            "group_id": "VG0001",
            "cue_index": 1,
            "phrase": "take a toll on",
            "meaning": "对……造成损害",
            "card_type": "standard",
        }],
        cues,
        groups,
    )

    assert plan[1]["word"] == "take a toll on"
    assert plan[1]["key"] == "take a toll on"


def test_vocab_source_phrase_does_not_match_inside_a_larger_word():
    cue = "She continues to out-earn her husband."

    assert podcast_learning_video.find_vocab_source_phrase(cue, "earn") == ""
    assert podcast_learning_video.find_vocab_source_phrase(cue, "out-earn") == "out-earn"


def test_vocab_plan_limits_concept_cards_to_three_per_episode():
    cues = [
        podcast_learning_video.Cue(index, (index - 1) * 20.0, (index - 1) * 20.0 + 2.0, f"Concept {index} appears.", "", "male")
        for index in range(1, 5)
    ]
    candidates = {
        index: {
            "key": f"concept {index}",
            "word": f"Concept {index}",
            "meaning": f"概念{index}",
            "detail": "需要额外解释。",
            "card_type": "concept",
            "priority": 5,
        }
        for index in range(1, 5)
    }

    plan = podcast_learning_video.schedule_vocab_card_plan(candidates, cues)

    assert sum(item["card_type"] == "concept" for item in plan.values()) == 3
    assert plan[4]["card_type"] == "standard"
    assert plan[4]["detail"] == ""


def test_vocab_plan_keeps_each_llm_card_inside_its_frozen_group():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 1.0, "The policy is designed", "", "male"),
        podcast_learning_video.Cue(2, 1.0, 2.0, "to reduce regulatory risk.", "", "male"),
        podcast_learning_video.Cue(3, 2.2, 3.2, "That is important.", "", "male"),
    ]
    groups = podcast_learning_video.build_vocab_semantic_groups(cues)
    assert [group.cue_indices for group in groups] == [(1, 2), (3,)]
    candidates = podcast_learning_video.normalize_vocab_plan(
        [
            {
                "group_id": "VG0001",
                "cue_index": 2,
                "word": "regulatory",
                "meaning": "监管的",
            }
        ],
        cues,
        groups,
    )
    plan = podcast_learning_video.schedule_vocab_card_plan(candidates, cues)
    assert plan[2]["display_start"] == 1.0
    assert podcast_learning_video.active_vocab_card(plan, cues[0], 0.5) is None
    assert podcast_learning_video.active_vocab_card(plan, cues[1], 1.0)["key"] == "regulatory"
    assert podcast_learning_video.active_vocab_card(plan, cues[2], 2.2)["key"] == "regulatory"
    assert podcast_learning_video.active_vocab_card(plan, None, 2.2)["key"] == "regulatory"


def test_article_vocab_card_starts_on_the_final_page_that_contains_its_phrase():
    cue = podcast_learning_video.Cue(
        1,
        10.0,
        18.0,
        "The opening context explains why employers eventually footed the bill.",
        "前文解释了为什么雇主最终承担了费用。",
        "male",
    )
    cue.article_page_plan = {
        "status": "ok",
        "pages": [
            {"en": "The opening context explains why employers", "start": 10.0, "end": 14.0},
            {"en": "eventually footed the bill.", "start": 14.0, "end": 18.0},
        ],
    }
    candidates = {
        1: {
            "key": "footed the bill",
            "word": "footed the bill",
            "meaning": "承担费用；买单",
            "priority": 5,
        }
    }

    ordinary_plan = podcast_learning_video.schedule_vocab_card_plan(candidates, [cue])
    article_plan = podcast_learning_video.schedule_vocab_card_plan(
        candidates,
        [cue],
        align_to_article_pages=True,
    )

    assert ordinary_plan[1]["display_start"] == 10.0
    assert article_plan[1]["display_start"] == 14.0
    assert podcast_learning_video.vocab_card_display_state(article_plan, cue, 13.999) == (
        None,
        "hidden",
    )
    assert podcast_learning_video.vocab_card_display_state(article_plan, cue, 14.0) == (
        article_plan[1],
        "full",
    )


def test_article_vocab_card_drops_a_phrase_split_across_final_pages():
    cue = podcast_learning_video.Cue(
        1,
        0.0,
        6.0,
        "They eventually footed the bill for everyone.",
        "他们最终为所有人买单。",
        "female",
    )
    cue.article_page_plan = {
        "status": "ok",
        "pages": [
            {"en": "They eventually footed", "start": 0.0, "end": 3.0},
            {"en": "the bill for everyone.", "start": 3.0, "end": 6.0},
        ],
    }
    candidates = {
        1: {
            "key": "footed the bill",
            "word": "footed the bill",
            "meaning": "承担费用；买单",
            "priority": 5,
        }
    }

    assert podcast_learning_video.schedule_vocab_card_plan(
        candidates,
        [cue],
        align_to_article_pages=True,
    ) == {}


def test_vocab_card_meaning_keeps_only_compact_primary_gloss():
    assert podcast_learning_video.compact_vocab_meaning(
        "n. 破绽；暴露真相的线索（此处指暴露 AI 的明显特征）"
    ) == "破绽；暴露真相的线索"
    assert podcast_learning_video.compact_vocab_meaning(
        "名词化（把动词或形容词变成名词的过程/结果）"
    ) == "名词化"


def test_vocab_plan_normalizes_verbose_model_meaning_before_rendering():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "A giveaway reveals the truth.", "", "male"),
    ]
    groups = podcast_learning_video.build_vocab_semantic_groups(cues)

    plan = podcast_learning_video.normalize_vocab_plan(
        [{
            "group_id": "VG0001",
            "cue_index": 1,
            "word": "giveaway",
            "meaning": "n. 破绽；暴露真相的线索（此处指暴露 AI 的明显特征）",
        }],
        cues,
        groups,
    )

    assert plan[1]["meaning"] == "破绽；暴露真相的线索"


def test_vocab_card_plan_skips_low_priority_model_candidates():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "A marginal word.", "", "male"),
        podcast_learning_video.Cue(2, 12.0, 14.0, "A central concept.", "", "male"),
    ]
    plan = podcast_learning_video.schedule_vocab_card_plan(
        {
            1: {"key": "marginal", "word": "Marginal", "priority": 2},
            2: {"key": "central", "word": "Central", "priority": 5},
        },
        cues,
    )

    assert list(plan) == [2]
    assert plan[2]["priority"] == 5


def test_vocab_card_plan_spreads_high_quality_candidates_across_the_episode():
    cue_starts = [10.0, 20.0, 30.0, 40.0, 50.0, 130.0, 250.0, 370.0, 490.0]
    cues = [
        podcast_learning_video.Cue(
            index,
            start,
            start + 2.0,
            f"Candidate {index} appears.",
            "",
            "male",
        )
        for index, start in enumerate(cue_starts, 1)
    ]
    cues.append(
        podcast_learning_video.Cue(10, 598.0, 600.0, "Closing remarks.", "", "female")
    )
    candidates = {
        cue.index: {
            "key": f"candidate {cue.index}",
            "word": f"Candidate {cue.index}",
            "priority": 5 if cue.start < 60.0 else 3,
        }
        for cue in cues[:-1]
    }

    plan = podcast_learning_video.schedule_vocab_card_plan(
        candidates,
        cues,
        max_cards=5,
    )

    assert [item["display_start"] for item in plan.values()] == [10.0, 130.0, 250.0, 370.0, 490.0]


def test_vocabulary_card_target_is_about_one_per_minute():
    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "Opening.", "", "male"),
        podcast_learning_video.Cue(2, 958.0, 960.0, "Closing.", "", "female"),
    ]
    assert podcast_learning_video.vocabulary_card_target(cues) == 16

    fifteen_minute_episode = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "Opening.", "", "male"),
        podcast_learning_video.Cue(2, 911.0, 913.0, "Closing.", "", "female"),
    ]
    assert podcast_learning_video.vocabulary_card_target(fifteen_minute_episode) == 15


def test_article_template_does_not_fallback_to_per_subtitle_vocab_lookup():
    article_image = Image.new(
        "RGB",
        (podcast_learning_video.acx(854), podcast_learning_video.acy(480)),
    )
    cue = podcast_learning_video.Cue(
        1,
        0.0,
        2.0,
        "A regulatory change.",
        "一次监管变化。",
        "male",
    )
    with patch.object(podcast_learning_video, "find_vocab", return_value={"key": "regulatory"}) as fallback, \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as draw_card:
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            vocab_plan={},
            show_vocab=True,
            display_time=0.5,
        )

    assert not fallback.called
    assert not draw_card.called


def test_vocab_generation_fails_closed_after_preserving_successful_batches():
    from types import SimpleNamespace

    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "An obscure signal appeared.", "出现了一个晦涩信号。", ""),
        podcast_learning_video.Cue(2, 2.1, 4.0, "The pattern is persistent.", "这种模式持续存在。", ""),
    ]
    groups = [
        podcast_learning_video.VocabSemanticGroup("VG0001", (1,), 0.0, 2.0, cues[0].en),
        podcast_learning_video.VocabSemanticGroup("VG0002", (2,), 2.1, 4.0, cues[1].en),
    ]

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("temporary provider failure")
            payload = [{
                "group_id": "VG0002",
                "cue_index": 2,
                "word": "persistent",
                "phonetic": "/pəˈsɪstənt/",
                "level": "IELTS",
                "pos": "adj.",
                "meaning": "持续的",
                "definition": "Continuing for a long time.",
                "tip_en": "A persistent pattern continues over time.",
                "tip_zh": "表示持续存在。",
            }]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    messages = []
    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=groups), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=[[groups[0]], [groups[1]]]
        ), patch.object(podcast_learning_video, "vocabulary_card_target", return_value=2), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("https://example.test/v1", "key", "test-model")
        ), patch.object(podcast_learning_video, "OpenAI", return_value=client), patch.object(
            podcast_learning_video, "CACHE_PATH", Path(raw) / "cache"
        ):
            try:
                podcast_learning_video.load_or_generate_vocab_plan(
                    subtitle_path,
                    cues,
                    True,
                    progress_callback=lambda _, message: messages.append(message),
                )
            except podcast_learning_video.VocabularyPlanIncompleteError as exc:
                assert exc.completed_chunks == 1
                assert exc.total_chunks == 2
            else:
                raise AssertionError("an incomplete vocabulary plan must block synthesis")

        progress = json.loads(
            podcast_learning_video.vocab_progress_cache_path(
                subtitle_path.with_suffix(".vocab_cards.json")
            ).read_text(encoding="utf-8")
        )

    assert progress["complete"] is False
    assert len(progress["completed_chunk_ids"]) == 1
    assert any("生成未完成（1/2 批）" in message for message in messages)


def test_empty_vocab_cache_is_regenerated_instead_of_reused():
    from types import SimpleNamespace

    cue = podcast_learning_video.Cue(
        1, 0.0, 2.0, "An obscure signal appeared.", "出现了一个晦涩信号。", ""
    )
    group = podcast_learning_video.VocabSemanticGroup(
        "VG0001", (1,), 0.0, 2.0, cue.en
    )

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            payload = [{
                "group_id": "VG0001",
                "cue_index": 1,
                "word": "obscure",
                "phonetic": "/əbˈskjʊr/",
                "level": "IELTS",
                "pos": "adj.",
                "meaning": "晦涩的",
                "definition": "Not well known or difficult to understand.",
                "tip_en": "Obscure can describe an idea that is hard to grasp.",
                "tip_zh": "可形容概念晦涩难懂。",
            }]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        cache_root = Path(raw) / "cache"
        source_hash = podcast_learning_video.vocab_source_hash([cue])
        stale_cache = cache_root / "podcast_vocab_cards" / f"{source_hash}.json"
        stale_cache.parent.mkdir(parents=True)
        stale_cache.write_text(
            json.dumps({
                "source_hash": source_hash,
                "prompt_version": podcast_learning_video.VOCAB_PROMPT_VERSION,
                "model": "test-model",
                "cards": [],
            }),
            encoding="utf-8",
        )
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=[group]), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=[[group]]
        ), patch.object(podcast_learning_video, "vocabulary_card_target", return_value=1), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("https://example.test/v1", "key", "test-model")
        ), patch.object(podcast_learning_video, "OpenAI", return_value=client), patch.object(
            podcast_learning_video, "CACHE_PATH", cache_root
        ):
            plan = podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, [cue], True)

    assert completions.calls == 1
    assert plan[1]["key"] == "obscure"


def test_vocab_request_batches_balance_timeline_coverage():
    groups = [
        podcast_learning_video.VocabSemanticGroup(
            f"VG{index + 1:04d}",
            (index + 1,),
            float(index),
            float(index + 1),
            f"Group {index + 1}",
        )
        for index in range(7)
    ]
    chunks = [[group] for group in groups]

    ordered = podcast_learning_video.order_vocab_request_chunks(chunks)

    assert [chunk[0].id for chunk in ordered[:5]] == [
        "VG0001",
        "VG0007",
        "VG0004",
        "VG0002",
        "VG0005",
    ]
    assert {chunk[0].id for chunk in ordered} == {group.id for group in groups}


def test_vocab_generation_resumes_only_unfinished_batches():
    from types import SimpleNamespace

    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "An obscure signal appeared.", "出现了一个晦涩信号。", ""),
        podcast_learning_video.Cue(2, 20.0, 22.0, "The pattern is persistent.", "这种模式持续存在。", ""),
    ]
    groups = [
        podcast_learning_video.VocabSemanticGroup("VG0001", (1,), 0.0, 2.0, cues[0].en),
        podcast_learning_video.VocabSemanticGroup("VG0002", (2,), 20.0, 22.0, cues[1].en),
    ]
    payloads = {
        "VG0001": [{
            "group_id": "VG0001",
            "cue_index": 1,
            "phrase": "obscure",
            "priority": 4,
            "meaning": "晦涩的",
        }],
        "VG0002": [{
            "group_id": "VG0002",
            "cue_index": 2,
            "phrase": "persistent",
            "priority": 4,
            "meaning": "持续的",
        }],
    }

    class FirstRunCompletions:
        calls = 0

        def create(self, **kwargs):
            self.calls += 1
            prompt = kwargs["messages"][1]["content"]
            if "VG0001" in prompt:
                raise RuntimeError("first batch unavailable")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payloads["VG0002"])))]
            )

    class ResumeCompletions:
        def __init__(self):
            self.prompts = []

        def create(self, **kwargs):
            prompt = kwargs["messages"][1]["content"]
            self.prompts.append(prompt)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payloads["VG0001"])))]
            )

    first = FirstRunCompletions()
    resumed = ResumeCompletions()
    clients = iter([
        SimpleNamespace(chat=SimpleNamespace(completions=first)),
        SimpleNamespace(chat=SimpleNamespace(completions=resumed)),
    ])
    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        cache_root = Path(raw) / "cache"
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=groups), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=[[groups[0]], [groups[1]]]
        ), patch.object(podcast_learning_video, "vocabulary_card_target", return_value=2), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("https://example.test/v1", "key", "test-model")
        ), patch.object(podcast_learning_video, "OpenAI", side_effect=lambda **_: next(clients)), patch.object(
            podcast_learning_video, "CACHE_PATH", cache_root
        ):
            try:
                podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, cues, True)
            except podcast_learning_video.VocabularyPlanIncompleteError as exc:
                assert exc.completed_chunks == 1
                assert exc.total_chunks == 2
            else:
                raise AssertionError("the first incomplete pass must fail closed")
            resumed_plan = podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, cues, True)

        progress_path = podcast_learning_video.vocab_progress_cache_path(
            subtitle_path.with_suffix(".vocab_cards.json")
        )
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        final_cache = json.loads(
            subtitle_path.with_suffix(".vocab_cards.json").read_text(encoding="utf-8")
        )

    assert set(resumed_plan) == {1, 2}
    assert len(resumed.prompts) == 1
    assert "VG0001" in resumed.prompts[0]
    assert "VG0002" not in resumed.prompts[0]
    assert progress["complete"] is True
    assert set(progress["completed_chunk_ids"]) == set(progress["chunk_order"])
    assert final_cache["cache_schema_version"] == podcast_learning_video.VOCAB_CACHE_SCHEMA_VERSION
    assert final_cache["complete"] is True


def test_successful_empty_vocab_batch_is_cached_as_complete():
    from types import SimpleNamespace

    cue = podcast_learning_video.Cue(
        1, 0.0, 2.0, "An ordinary sentence appeared.", "出现了一个普通句子。", ""
    )
    group = podcast_learning_video.VocabSemanticGroup(
        "VG0001", (1,), 0.0, 2.0, cue.en
    )

    class EmptyCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))]
            )

    completions = EmptyCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        cache_root = Path(raw) / "cache"
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=[group]), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=[[group]]
        ), patch.object(podcast_learning_video, "vocabulary_card_target", return_value=1), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("https://example.test/v1", "key", "test-model")
        ), patch.object(podcast_learning_video, "OpenAI", return_value=client), patch.object(
            podcast_learning_video, "CACHE_PATH", cache_root
        ):
            assert podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, [cue], True) == {}
            assert podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, [cue], True) == {}

        cached = json.loads(
            subtitle_path.with_suffix(".vocab_cards.json").read_text(encoding="utf-8")
        )

    assert completions.calls == 1
    assert cached["complete"] is True
    assert len(cached["completed_chunk_ids"]) == 1
    assert cached["chunks"][cached["completed_chunk_ids"][0]]["cards"] == []


def test_atomic_vocab_cache_write_preserves_previous_file_on_replace_failure():
    with tempfile.TemporaryDirectory() as raw:
        target = Path(raw) / "cache.json"
        target.write_text('{"old": true}', encoding="utf-8")

        with patch.object(Path, "replace", side_effect=OSError("replace failed")):
            written = podcast_learning_video.atomic_write_vocab_cache(
                target,
                {"new": True},
            )

        assert written is False
        assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}


def test_legacy_vocab_cache_cannot_authorize_an_incomplete_render():
    from types import SimpleNamespace

    cues = [
        podcast_learning_video.Cue(1, 0.0, 2.0, "An obscure signal appeared.", "出现了一个晦涩信号。", ""),
        podcast_learning_video.Cue(2, 20.0, 22.0, "The pattern is persistent.", "这种模式持续存在。", ""),
    ]
    groups = [
        podcast_learning_video.VocabSemanticGroup("VG0001", (1,), 0.0, 2.0, cues[0].en),
        podcast_learning_video.VocabSemanticGroup("VG0002", (2,), 20.0, 22.0, cues[1].en),
    ]
    new_card = [{
        "group_id": "VG0002",
        "cue_index": 2,
        "phrase": "persistent",
        "priority": 4,
        "meaning": "持续的",
    }]

    class PartialCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(new_card)))]
                )
            raise RuntimeError("later batch unavailable")

    completions = PartialCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        cache_root = Path(raw) / "cache"
        source_hash = podcast_learning_video.vocab_source_hash(cues)
        legacy_path = subtitle_path.with_suffix(".vocab_cards.json")
        legacy_payload = {
            "source_hash": source_hash,
            "prompt_version": podcast_learning_video.VOCAB_PROMPT_VERSION,
            "model": "test-model",
            "cards": [{
                "group_id": "VG0001",
                "cue_index": 1,
                "word": "obscure",
                "priority": 4,
                "meaning": "晦涩的",
            }],
        }
        legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=groups), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=[[groups[1]], [groups[0]]]
        ), patch.object(podcast_learning_video, "vocabulary_card_target", return_value=2), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("https://example.test/v1", "key", "test-model")
        ), patch.object(podcast_learning_video, "OpenAI", return_value=client), patch.object(
            podcast_learning_video, "CACHE_PATH", cache_root
        ):
            try:
                podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, cues, True)
            except podcast_learning_video.VocabularyPlanIncompleteError as exc:
                assert exc.completed_chunks == 1
                assert exc.total_chunks == 2
            else:
                raise AssertionError("legacy cards must not authorize an incomplete render")

        unchanged_legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        progress = json.loads(
            podcast_learning_video.vocab_progress_cache_path(legacy_path).read_text(encoding="utf-8")
        )

    assert unchanged_legacy == legacy_payload
    assert progress["complete"] is False
    assert len(progress["completed_chunk_ids"]) == 1


def test_incomplete_vocab_cache_without_model_configuration_fails_closed():
    cue = podcast_learning_video.Cue(
        1, 0.0, 2.0, "An obscure signal appeared.", "出现了一个晦涩信号。", ""
    )
    groups = [
        podcast_learning_video.VocabSemanticGroup("VG0001", (1,), 0.0, 1.0, cue.en),
        podcast_learning_video.VocabSemanticGroup("VG0002", (1,), 1.0, 2.0, cue.en),
    ]
    chunks = [[group] for group in groups]

    with tempfile.TemporaryDirectory() as raw:
        subtitle_path = Path(raw) / "sample.srt"
        subtitle_path.write_text("", encoding="utf-8")
        cache_root = Path(raw) / "cache"
        chunk_order = [
            podcast_learning_video.vocab_request_chunk_id(chunk) for chunk in chunks
        ]
        progress_path = podcast_learning_video.vocab_progress_cache_path(
            subtitle_path.with_suffix(".vocab_cards.json")
        )
        podcast_learning_video.atomic_write_vocab_cache(
            progress_path,
            {
                "cache_schema_version": podcast_learning_video.VOCAB_CACHE_SCHEMA_VERSION,
                "source_hash": podcast_learning_video.vocab_source_hash([cue]),
                "prompt_version": podcast_learning_video.VOCAB_PROMPT_VERSION,
                "model": "",
                "complete": False,
                "chunk_order": chunk_order,
                "completed_chunk_ids": [chunk_order[0]],
                "chunks": {
                    chunk_order[0]: {
                        "group_ids": [groups[0].id],
                        "cards": [],
                    }
                },
            },
        )
        with patch.object(podcast_learning_video, "build_vocab_semantic_groups", return_value=groups), patch.object(
            podcast_learning_video, "split_vocab_groups_for_requests", return_value=chunks
        ), patch.object(
            podcast_learning_video, "current_llm_config", return_value=("", "", "")
        ), patch.object(podcast_learning_video, "CACHE_PATH", cache_root):
            try:
                podcast_learning_video.load_or_generate_vocab_plan(subtitle_path, [cue], True)
            except podcast_learning_video.VocabularyPlanIncompleteError as exc:
                assert exc.completed_chunks == 1
                assert exc.total_chunks == 2
            else:
                raise AssertionError("missing model configuration must not reuse partial cards")


def test_incomplete_vocab_plan_blocks_renderer_before_ffmpeg():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subtitle_path = root / "sample.srt"
        subtitle_path.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nA short cue.\n一条短字幕。\n",
            encoding="utf-8",
        )
        failure = podcast_learning_video.VocabularyPlanIncompleteError(1, 2)
        with patch.object(
            podcast_learning_video,
            "load_or_generate_vocab_plan",
            side_effect=failure,
        ), patch.object(podcast_learning_video.subprocess, "Popen") as popen:
            try:
                podcast_learning_video.render_podcast_learning_video(
                    "unused-source.m4a",
                    str(subtitle_path),
                    str(root / "output.mp4"),
                    show_ai_vocab=True,
                )
            except podcast_learning_video.VocabularyPlanIncompleteError:
                pass
            else:
                raise AssertionError("renderer must propagate an incomplete vocabulary plan")

        assert not popen.called


def test_article_template_requests_page_aligned_vocab_plan_before_ffmpeg():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        subtitle_path = root / "article.srt"
        subtitle_path.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nA paginated expression.\n一个分页表达。\n",
            encoding="utf-8",
        )
        failure = podcast_learning_video.VocabularyPlanIncompleteError(1, 2)
        with patch.object(
            podcast_learning_video,
            "prepare_article_visual_page_plans",
        ), patch.object(
            podcast_learning_video,
            "load_or_generate_vocab_plan",
            side_effect=failure,
        ) as load_plan, patch.object(
            podcast_learning_video.subprocess,
            "Popen",
        ) as popen:
            try:
                podcast_learning_video.render_podcast_learning_video(
                    "unused-source.m4a",
                    str(subtitle_path),
                    str(root / "output.mp4"),
                    template_style="文章单词",
                    show_ai_vocab=True,
                )
            except podcast_learning_video.VocabularyPlanIncompleteError:
                pass
            else:
                raise AssertionError("renderer must propagate an incomplete vocabulary plan")

        assert load_plan.call_args.kwargs["align_to_article_pages"] is True
        assert not popen.called


def test_article_template_shows_topic_panel_before_first_card():
    article_image = Image.new(
        "RGB",
        (podcast_learning_video.acx(854), podcast_learning_video.acy(480)),
    )
    cue = podcast_learning_video.Cue(1, 0.0, 8.0, "Welcome to the lesson.", "欢迎收看本期内容。", "male")
    plan = {
        2: {
            "key": "regulatory",
            "word": "Regulatory",
            "meaning": "监管的",
            "display_start": 4.0,
            "display_end": 7.0,
        }
    }
    with patch.object(podcast_learning_video, "draw_article_opening_topic_panel") as topic_panel, \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as card:
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            plan,
            show_vocab=True,
            title_text="如何识别人工智能写作",
            display_time=0.0,
        )
        assert topic_panel.called
        assert topic_panel.call_args.args[2] == "如何识别人工智能写作"
        assert not card.called

        topic_panel.reset_mock()
        podcast_learning_video.draw_article_frame(article_image, cue, plan, show_vocab=True, display_time=5.0)
        assert card.called
        assert not topic_panel.called

        card.reset_mock()
        podcast_learning_video.draw_article_frame(article_image, cue, plan, show_vocab=True, display_time=8.0)
        assert card.called
        assert not topic_panel.called


def test_article_template_first_vocab_card_is_full_strength_at_trigger_time():
    article_image = Image.new(
        "RGB",
        (podcast_learning_video.acx(854), podcast_learning_video.acy(480)),
    )
    cue = podcast_learning_video.Cue(1, 4.0, 6.0, "A key expression appears.", "出现一个重点表达。", "male")
    plan = {
        1: {"key": "key expression", "word": "key expression", "meaning": "重点表达", "display_start": 4.0, "display_end": 12.0},
        2: {"key": "next expression", "word": "next expression", "meaning": "下一个表达", "display_start": 24.0, "display_end": 32.0},
    }
    with patch.object(podcast_learning_video, "draw_article_opening_topic_panel") as topic_panel, \
         patch.object(podcast_learning_video, "draw_article_vocab_card") as card, \
         patch.object(podcast_learning_video.Image, "blend") as blend:
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            plan,
            show_vocab=True,
            display_time=4.0,
        )
        assert card.called
        assert card.call_args.args[1] == plan[1]
        assert not topic_panel.called
        assert not blend.called

        topic_panel.reset_mock()
        card.reset_mock()
        podcast_learning_video.draw_article_frame(
            article_image,
            cue,
            plan,
            show_vocab=True,
            display_time=24.0,
        )
        assert not topic_panel.called
        assert card.called
        assert card.call_args.args[1] == plan[2]
        assert not blend.called


def test_episode_vocab_overview_uses_editor_rank_instead_of_earliest_words():
    plan = {
        3: {"word": "Early", "display_start": 2.0},
        21: {"word": "Core", "display_start": 40.0, "episode_rank": 1},
        48: {"word": "Theme", "display_start": 90.0, "episode_rank": 2},
        77: {"word": "Mechanism", "display_start": 140.0, "episode_rank": 3},
    }

    assert [item["word"] for item in podcast_learning_video.episode_vocab_overview_items(plan)] == [
        "Core",
        "Theme",
        "Mechanism",
    ]


def test_template_frame_cache_keeps_the_full_vocab_card_stable():
    class _FakeStdin:
        def write(self, payload):
            pass

        def close(self):
            pass

    class _FakeProcess:
        def __init__(self):
            self.stdin = _FakeStdin()

        def wait(self):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("successful template process must not be killed")

    plan = {
        1: {
            "key": "regulatory",
            "word": "Regulatory",
            "display_id": "1:regulatory",
            "display_start": 0.0,
        }
    }
    rendered_at = []

    def draw_frame(*args):
        rendered_at.append(args[-1])
        return Image.new("RGB", (2, 2))

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        srt = root / "long.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:10,000\nA regulatory change.\n一次监管变化。\n",
            encoding="utf-8",
        )
        process = _FakeProcess()

        def _start_fake_process(command, *args, **kwargs):
            Path(command[-1]).write_bytes(b"fake-video")
            return process

        with patch.object(podcast_learning_video, "load_or_generate_vocab_plan", return_value=plan), \
             patch.object(podcast_learning_video, "get_duration", return_value=10.0), \
             patch.object(podcast_learning_video, "FPS", 1), \
             patch.object(podcast_learning_video, "make_base", return_value=Image.new("RGBA", (2, 2))), \
             patch.object(podcast_learning_video, "make_avatars", return_value=(None, None)), \
             patch.object(podcast_learning_video, "draw_frame", side_effect=draw_frame), \
             patch.object(podcast_learning_video.subprocess, "Popen", side_effect=_start_fake_process):
            podcast_learning_video.render_podcast_learning_video(
                "source.m4a",
                str(srt),
                str(root / "output.mp4"),
                show_ai_vocab=True,
            )

    assert rendered_at
    assert all(timestamp < 8.0 for timestamp in rendered_at)


def test_stable_srt_writer_keeps_bilingual_original_top():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "stable-final-original-top.srt"
        data = ASRData([ASRDataSeg("Hello world.", 0, 1000, "你好，世界。")])

        SubtitleThread._write_stable_srt(data, path, "original_top")

        text = path.read_text(encoding="utf-8-sig")
        assert "Hello world.\n你好，世界。" in text


def test_id_bound_group_missing_one_id_does_not_shift_later_subtitles():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(4, translated="fallback-S{index:04d}"))
    group = _id_group(1, 0, items)
    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0004", "zh": "zh-S0004"},
        ],
    )

    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})

    assert [item.subtitle_id for item in applied] == ["S0001", "S0002", "S0003", "S0004"]
    assert [item.original for item in applied] == [item.original for item in items]
    assert [item.word_start for item in applied] == [item.word_start for item in items]
    assert applied[2].translated == "fallback-S0003"
    assert applied[3].translated == "zh-S0004"
    assert {"translation_id_missing", "translation_group_cardinality_mismatch"} <= _codes(editor)


def test_atomic_no_response_cannot_be_written_as_affirmative():
    editor = _editor()

    assert editor._repair_atomic_response_polarity("No.", "对。") == "不是。"
    assert editor._repair_atomic_response_polarity("No.", "不。") == "不。"
    assert editor._repair_atomic_response_polarity("No, not at all.", "完全不是。") == "完全不是。"


def test_id_bound_group_rejects_duplicate_id_without_compressing_chinese():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(3))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0002", "zh": "duplicate"},
        ],
    )

    assert translations == {"S0001": "zh-S0001", "S0002": "zh-S0002"}
    assert {
        "translation_id_duplicate",
        "translation_id_missing",
        "translation_group_cardinality_mismatch",
    } <= _codes(editor)


def test_id_bound_group_rejects_unknown_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S9999", "zh": "unknown"},
        ],
    )

    assert translations == {"S0001": "zh-S0001"}
    assert {
        "translation_id_unknown",
        "translation_id_missing",
        "translation_group_cardinality_mismatch",
    } <= _codes(editor)


def test_id_bound_allocation_rejects_terminal_modifier_fragment():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "他认为，人工智能创造的巨大价值不会只被硅谷的少数科技巨头吞掉。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "He argues the value will not be swallowed up"},
            {"subtitle_id": "S0002", "english": "by tech giants in Silicon Valley."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "他认为，巨大的价值不会只被科技巨头吞掉", "S0002": "尤其是硅谷的。"},
    )

    assert not validation["valid"]
    assert "unnatural_chinese_fragment" in validation["issue_codes"]


def test_id_bound_allocation_accepts_terminal_shi_de_predicate():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "也就是用来突然打断自己思路的标点符号，那肯定是AI写的。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Those are the marks people use to interrupt themselves"},
            {"subtitle_id": "S0002", "english": "so it must have been written by AI."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "也就是用来突然打断自己思路的标点符号，",
            "S0002": "那肯定是AI写的。",
        },
    )

    assert validation["valid"]
    assert "unnatural_chinese_fragment" not in validation["issue_codes"]


def test_id_bound_allocation_accepts_conditional_modifier_before_following_question():
    editor = _id_editor()
    entry = {
        "id": 4,
        "full_translation": "如果制造环节的每一块拼图本质上都是中国的，那最终组装的产品到底从哪一刻起才算越南制造？",
        "subtitle_parts": [
            {"subtitle_id": "S0005", "english": "If every piece is intrinsically Chinese,"},
            {"subtitle_id": "S0006", "english": "at what point does the product become Vietnamese?"},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0005": "如果制造环节的每一块拼图本质上都是中国的，",
            "S0006": "那最终组装的产品到底从哪一刻起才算越南制造？",
        },
    )

    assert validation["valid"]
    assert "unnatural_chinese_fragment" not in validation["issue_codes"]


def test_id_bound_allocation_accepts_terminal_shi_de_creation_predicate():
    editor = _id_editor()
    entry = {
        "id": 23,
        "full_translation": "这个体系是美国自己于1940年代参与缔造的全球贸易体系。",
        "subtitle_parts": [
            {"subtitle_id": "S0030", "english": "It altered a global trading system"},
            {"subtitle_id": "S0031", "english": "that America helped author."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0030": "因为它彻底改变了全球贸易体系",
            "S0031": "这个体系是美国自己于1940年代参与缔造的。",
        },
    )

    assert validation["valid"]
    assert "unnatural_chinese_fragment" not in validation["issue_codes"]


def test_terminal_modifier_fragment_uses_specialized_fixed_id_retry():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "The value will not be swallowed up"
    items[1].original = "by Silicon Valley tech giants."
    group = _id_group(1, 0, items)
    full_translations = {
        1: "这些价值不会只被硅谷的少数科技巨头吞掉。",
    }
    calls = []

    def request(
        prompt,
        payload,
        cache_task,
        expected_groups_by_id=None,
        **kwargs,
    ):
        calls.append((prompt, cache_task))
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [{
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "这些价值不会只被科技巨头吞掉"},
                        {"subtitle_id": "S0002", "zh": "尤其是硅谷的。"},
                    ],
                }]
            }
        assert cache_task == "screen_subtitle_semantic_translation_allocation_fragment_retry_v1"
        assert "bare modifier" in prompt
        return {
            "groups": [{
                "id": 1,
                "part_translations": [
                    {"subtitle_id": "S0001", "zh": "这些价值不会只被吞掉，"},
                    {"subtitle_id": "S0002", "zh": "也不会只落入硅谷科技巨头之手。"},
                ],
            }]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations([group], full_translations)

    assert allocated[1] == {
        "S0001": "这些价值不会只被吞掉，",
        "S0002": "也不会只落入硅谷科技巨头之手。",
    }
    assert [task for _, task in calls] == [
        "screen_subtitle_semantic_translation_allocation_v3",
        "screen_subtitle_semantic_translation_allocation_fragment_retry_v1",
    ]


def test_semantic_audit_does_not_flag_a_complete_single_cue_as_a_fragment():
    editor = _id_editor()

    findings = editor._chinese_group_quality_findings(
        "The boom is entirely broad-based.",
        "这轮增长完全是全面开花的。",
        ["这轮增长完全是全面开花的。"],
        full_translation="这轮增长完全是全面开花的。",
        mapping_valid=True,
    )

    assert not {
        finding["code"] for finding in findings
    } & {"missing_predicate", "dangling_preposition"}


def test_id_bound_group_allows_different_return_order():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(4))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0004", "zh": "zh-S0004"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0003", "zh": "zh-S0003"},
        ],
    )
    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})

    assert [item.translated for item in applied] == [
        "zh-S0001",
        "zh-S0002",
        "zh-S0003",
        "zh-S0004",
    ]
    assert editor._translation_structure_errors == []


def test_allocation_parser_recovers_orphan_subtitle_rows_by_global_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [_id_group(1, 0, items[:2]), _id_group(2, 2, items[2:])]
    groups_data = [
        {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [{"subtitle_id": "S0001", "zh": "zh-S0001"}],
                },
                {"subtitle_id": "S0002", "zh": "zh-S0002"},
            ]
        },
        {
            "id": 2,
            "part_translations": [{"subtitle_id": "S0003", "zh": "zh-S0003"}],
        },
        {"subtitle_id": "S0004", "zh": "zh-S0004"},
    ]

    normalized = editor._normalize_allocation_groups_data(groups, groups_data)
    translations = {}
    for group in normalized:
        expected_group = groups[int(group["id"]) - 1]
        translations[int(group["id"])] = editor._parse_id_bound_translations(
            expected_group,
            editor._group_expected_subtitle_ids(expected_group),
            group.get("part_translations", []),
        )
    applied = editor._apply_semantic_group_translations(items, groups, translations)

    assert [item.subtitle_id for item in applied] == ["S0001", "S0002", "S0003", "S0004"]
    assert [item.translated for item in applied] == [
        "zh-S0001",
        "zh-S0002",
        "zh-S0003",
        "zh-S0004",
    ]
    assert editor._translation_structure_errors == []


def test_allocation_requests_large_payload_in_small_id_bound_chunks():
    editor = _id_editor()
    editor.batch_num = 50
    editor.allocation_batch_size = 24
    items = editor._assign_global_subtitle_ids(_id_items(50))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 26)
    ]
    full_translations = {
        index: f"译文S{index * 2 - 1:04d}译文S{index * 2:04d}"
        for index in range(1, 26)
    }
    requested_group_ids = []

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation",
        **kwargs,
    ):
        requested_group_ids.append([entry["id"] for entry in payload])
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": part["subtitle_id"],
                            "zh": f"译文{part['subtitle_id']}",
                        }
                        for part in entry["subtitle_parts"]
                    ],
                }
                for entry in reversed(payload)
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert requested_group_ids == [
        list(range(1, 25)),
        [25],
    ]
    assert allocated[1] == {"S0001": "译文S0001", "S0002": "译文S0002"}
    assert allocated[25] == {"S0049": "译文S0049", "S0050": "译文S0050"}
    assert editor._translation_structure_errors == []


def test_allocation_retry_preserves_initial_fixed_id_protocol_evidence():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    group = _id_group(1, 0, items)
    frozen_fields = [
        (item.subtitle_id, item.original, item.word_start, item.word_end)
        for item in items
    ]
    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation",
        **kwargs,
    ):
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "这是一条完整内容。"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "这是一条完整内容。"},
                        {"subtitle_id": "S0002", "zh": "这是另一条完整内容。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(
            [group],
            {1: "这是一条完整内容。这是另一条完整内容。"},
        )

    assert allocated == {
        1: {"S0001": "这是一条完整内容。", "S0002": "这是另一条完整内容。"}
    }
    assert [
        (item.subtitle_id, item.original, item.word_start, item.word_end)
        for item in items
    ] == frozen_fields
    assert editor._translation_structure_errors == []
    attempt_records = [
        record
        for record in editor._last_allocation_validation
        if record.get("record_type") == "allocation_structure_attempt"
    ]
    assert attempt_records == [
        {
            "record_type": "allocation_structure_attempt",
            "status": "retry_required",
            "stage": "initial_batch",
            "expected_semantic_group_ids": [1],
            "errors": [
                {
                    "code": "translation_id_missing",
                    "message": "Missing translation subtitle_id(s).",
                    "semantic_group_id": "G0001",
                    "expected_subtitle_ids": ["S0001", "S0002"],
                    "returned_subtitle_ids": ["S0001"],
                    "duplicate_subtitle_ids": [],
                    "unknown_subtitle_ids": [],
                    "missing_subtitle_ids": ["S0002"],
                },
                {
                    "code": "translation_group_cardinality_mismatch",
                    "message": "Returned subtitle_id set does not match expected subtitle_id set.",
                    "semantic_group_id": "G0001",
                    "expected_subtitle_ids": ["S0001", "S0002"],
                    "returned_subtitle_ids": ["S0001"],
                    "duplicate_subtitle_ids": [],
                    "unknown_subtitle_ids": [],
                    "missing_subtitle_ids": ["S0002"],
                },
            ],
        }
    ]


def test_allocation_final_artifact_keeps_unresolved_group_fixed_id_mapping():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(3))
    groups = [_id_group(1, 0, items[:2]), _id_group(2, 2, items[2:])]
    editor._last_allocation_final = [
        {
            "semantic_group_id": "G0001",
            "subtitle_ids": ["S0001", "S0002"],
            "allocation": {"S0001": "中文一", "S0002": "中文二"},
            "source": "initial",
        }
    ]
    items[0].translated = "中文一"
    items[1].translated = "中文二"
    items[2].translated = "保留的中文三"

    payload = editor._final_allocation_payload(groups, items)

    assert payload == [
        {
            "semantic_group_id": "G0001",
            "subtitle_ids": ["S0001", "S0002"],
            "allocation": {"S0001": "中文一", "S0002": "中文二"},
            "source": "initial",
        },
        {
            "semantic_group_id": "G0002",
            "subtitle_ids": ["S0003"],
            "allocation": {"S0003": "保留的中文三"},
            "source": "unresolved_final_subtitle_items",
        },
    ]


def test_single_cue_group_uses_authoritative_full_translation_without_allocation_request():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Hello."
    items[1].original = "Thanks."
    groups = [_id_group(1, 0, [items[0]]), _id_group(2, 1, [items[1]])]

    with patch.object(
        editor,
        "_request_semantic_translation_allocation",
        side_effect=AssertionError("single-cue group must not make an allocation request"),
    ):
        allocated = editor._allocate_semantic_group_translations(
            groups,
            {1: "你好。", 2: "谢谢。"},
        )

    assert allocated == {1: {"S0001": "你好。"}, 2: {"S0002": "谢谢。"}}
    assert [entry["source"] for entry in editor._last_allocation_final] == [
        "authoritative_full_translation",
        "authoritative_full_translation",
    ]
    assert editor._last_allocation_retry_log == []
    assert [entry["id"] for entry in editor._last_allocation_inputs] == [1, 2]


def test_single_cue_authoritative_translation_ending_in_de_is_not_an_allocation_fragment():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(1))
    items[0].original = "But the evidence suggests machines do not write that way today."
    group = _id_group(1, 0, items)
    chinese = "但数据表明，眼下机器根本不是那样写作的。"

    allocated = editor._allocate_semantic_group_translations([group], {1: chinese})

    assert allocated == {1: {"S0001": chinese}}
    assert not editor._last_allocation_unresolved


def test_just_because_non_entailment_translation_is_not_semantic_loss():
    editor = _id_editor()
    english = (
        "Just because human microbiomes differ significantly from person to person "
        "does not mean an era of personalized microbiome medicine has actually arrived."
    )
    chinese = "人类微生物组个体差异大，不等于个性化微生物医学时代已到来。"

    findings = editor._chinese_group_quality_findings(
        english,
        chinese,
        [chinese],
        full_translation=chinese,
        mapping_valid=True,
    )

    assert "semantic_loss" not in {finding["code"] for finding in findings}


def test_invalid_single_cue_quality_preserves_authoritative_translation_for_review():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    groups = [_id_group(1, 0, [items[0]]), _id_group(2, 1, [items[1]])]

    def validate(entry, allocation, **_kwargs):
        return {
            "semantic_group_id": f"G{entry['id']:04d}",
            "valid": entry["id"] != 1,
            "issue_codes": ["full_translation_quality_issue"] if entry["id"] == 1 else [],
            "issues": [],
        }

    with patch.object(editor, "_validate_group_chinese_allocation", side_effect=validate):
        allocated = editor._allocate_semantic_group_translations(
            groups,
            {1: "无效完整翻译", 2: "保留第二组翻译。"},
        )

    assert allocated == {
        1: {"S0001": "无效完整翻译"},
        2: {"S0002": "保留第二组翻译。"},
    }
    assert editor._last_allocation_unresolved[0]["semantic_group_id"] == "G0001"
    assert editor._last_allocation_unresolved[0]["allocation"] == {
        "S0001": "无效完整翻译"
    }


def test_missing_full_translation_does_not_discard_prior_fixed_id_allocation():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    groups = [_id_group(1, 0, [items[0]]), _id_group(2, 1, [items[1]])]

    allocated = editor._allocate_semantic_group_translations(
        groups,
        {1: "保留第一组翻译。"},
    )

    assert allocated == {1: {"S0001": "保留第一组翻译。"}}
    assert editor._translation_structure_errors[-1] == {
        "code": "translation_group_cardinality_mismatch",
        "message": "Semantic full translation is missing for the fixed-ID group.",
        "semantic_group_id": "G0002",
        "expected_subtitle_ids": ["S0002"],
        "returned_subtitle_ids": [],
        "duplicate_subtitle_ids": [],
        "unknown_subtitle_ids": [],
        "missing_subtitle_ids": ["S0002"],
    }
    assert editor._last_allocation_unresolved[-1]["reason"] == "authoritative_full_translation_missing"


def test_full_translation_number_error_is_not_misclassified_as_allocation_error():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "下降了8个百分点。",
        "subtitle_parts": [{"subtitle_id": "S0001", "english": "An 8% drop."}],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "下降了8个百分点。"},
    )

    assert validation["valid"]
    assert "full_translation_quality_issue" in validation["issue_codes"]
    assert "number_allocation_mismatch" not in validation["issue_codes"]


def test_full_translation_requests_are_chunked_and_retry_missing_groups():
    editor = _id_editor()
    editor.batch_num = 12
    editor.allocation_batch_size = 12
    items = editor._assign_global_subtitle_ids(_id_items(12))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 13)]
    calls = []

    def request(prompt, payload, cache_task, **kwargs):
        ids = [entry["id"] for entry in payload]
        calls.append((cache_task, ids))
        if ids == list(range(1, 9)):
            return {
                "groups": [
                    {
                        "id": 1,
                        "source_english": payload[0]["full_english"],
                        "full_translation": "full-1",
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "source_english": entry["full_english"],
                    "full_translation": f"full-{entry['id']}",
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_full_translation_chunk", side_effect=request):
        full_translations = editor._translate_semantic_group_full_translations(groups)

    assert calls == [
        ("screen_subtitle_semantic_full_translation_v7", list(range(1, 9))),
        ("screen_subtitle_semantic_full_translation_v7", [9, 10, 11, 12]),
        ("screen_subtitle_semantic_full_translation_v7_retry", list(range(2, 9))),
    ]
    assert full_translations == {
        group_id: f"full-{group_id}" for group_id in range(1, 13)
    }
    assert editor._translation_structure_errors == []


def test_full_translation_missing_group_repair_has_a_hard_request_budget():
    editor = _id_editor()
    editor.batch_num = 24
    editor.allocation_batch_size = 24
    items = editor._assign_global_subtitle_ids(_id_items(48))
    groups = [_id_group(index, index - 1, [items[index - 1]]) for index in range(1, 49)]
    calls = []

    def request(prompt, payload, cache_task, **kwargs):
        calls.append((cache_task, [entry["id"] for entry in payload]))
        return {"groups": []}

    with patch.object(editor, "_request_semantic_full_translation_chunk", side_effect=request):
        full_translations = editor._translate_semantic_group_full_translations(groups)

    retry_calls = [call for call in calls if call[0].endswith("_retry")]
    assert full_translations == {}
    assert len(retry_calls) == 12
    assert all(1 <= len(ids) <= 8 for _task, ids in retry_calls)
    assert {
        issue["semantic_group_id"] for issue in editor._translation_structure_errors
    } == {f"G{group_id:04d}" for group_id in range(1, 49)}


def test_full_translation_source_echo_is_required_per_generated_group():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    groups = [_id_group(1, 0, items)]
    payload = [editor._semantic_full_translation_payload_entry(groups, 0)]
    valid = {
        "groups": [
            {
                "id": 1,
                "source_english": "English 1. English 2.",
                "full_translation": "完整中文。",
            }
        ]
    }
    missing_echo = {
        "groups": [{"id": 1, "full_translation": "完整中文。"}]
    }
    wrong_echo = {
        "groups": [
            {
                "id": 1,
                "source_english": "English 2. English 1.",
                "full_translation": "完整中文。",
            }
        ]
    }

    assert editor._semantic_full_translation_response_is_cacheable(valid, payload)
    assert not editor._semantic_full_translation_response_is_cacheable(missing_echo, payload)
    assert not editor._semantic_full_translation_response_is_cacheable(wrong_echo, payload)
    assert editor._semantic_full_translations_from_response(missing_echo, payload=payload) == {}
    assert editor._semantic_full_translations_from_response(valid, payload=payload) == {
        1: "完整中文。"
    }


def test_full_translation_payload_adds_bounded_read_only_neighbor_context():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [
        _id_group(index, index - 1, [items[index - 1]])
        for index in range(1, 5)
    ]

    first = editor._semantic_full_translation_payload_entry(groups, 0)
    middle = editor._semantic_full_translation_payload_entry(groups, 2)
    last = editor._semantic_full_translation_payload_entry(groups, 3)

    assert first["translation_context_version"] == (
        "semantic-full-translation-context-v1"
    )
    assert first["translation_context"]["previous"] == []
    assert [item["semantic_group_id"] for item in first["translation_context"]["next"]] == [
        "G0002",
        "G0003",
    ]
    assert [item["semantic_group_id"] for item in middle["translation_context"]["previous"]] == [
        "G0001",
        "G0002",
    ]
    assert [item["semantic_group_id"] for item in middle["translation_context"]["next"]] == [
        "G0004",
    ]
    assert [item["semantic_group_id"] for item in last["translation_context"]["previous"]] == [
        "G0002",
        "G0003",
    ]
    context_entry = middle["translation_context"]["previous"][0]
    assert context_entry["context_only"] is True
    assert context_entry["subtitle_ids"] == ["S0001"]
    assert "id" not in context_entry


def test_full_translation_payload_includes_fixed_id_soft_reading_budgets():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(
        [
            ScreenSubtitleItem(
                source_ids=[1],
                original="The main takeaway is clear.",
                translated="",
                word_start=0,
                word_end=2,
            ),
            ScreenSubtitleItem(
                source_ids=[2],
                original="The system can respond faster.",
                translated="",
                word_start=3,
                word_end=5,
            ),
        ]
    )
    editor._active_word_entries = [
        {"start_time": 0, "end_time": 300},
        {"start_time": 350, "end_time": 800},
        {"start_time": 850, "end_time": 1500},
        {"start_time": 1600, "end_time": 2100},
        {"start_time": 2150, "end_time": 2800},
        {"start_time": 2850, "end_time": 3600},
    ]
    groups = [_id_group(1, 0, items)]

    payload = editor._semantic_full_translation_payload_entry(groups, 0)

    assert payload["subtitle_parts"] == [
        {
            "subtitle_id": "S0001",
            "english": "The main takeaway is clear.",
            "duration_ms": 1500,
            "max_zh_chars": 18,
            "target_zh_chars": 12,
            "absolute_max_zh_chars": 18,
        },
        {
            "subtitle_id": "S0002",
            "english": "The system can respond faster.",
            "duration_ms": 2000,
            "max_zh_chars": 18,
            "target_zh_chars": 16,
            "absolute_max_zh_chars": 18,
        },
    ]
    assert payload["translation_budget"] == {
        "budget_basis": "sum_of_fixed_subtitle_display_durations",
        "target_zh_chars": 28,
        "absolute_max_zh_chars": 36,
    }


def test_full_translation_prompt_restrains_ordinary_chinese_em_dashes():
    from app.core.subtitle_processor.screen_editor import (
        SEMANTIC_FULL_TRANSLATION_CACHE_TASK,
        SEMANTIC_FULL_TRANSLATION_PROMPT,
        SEMANTIC_FULL_TRANSLATION_PROMPT_VERSION,
    )

    assert "Do not use em dashes for ordinary explanations" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "Never leave an em dash at the beginning or end" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "one-glance video subtitle" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "Remove meaning-free conversational scaffolding" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "attached acknowledgement" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "standalone response" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "Do not remove a reaction, hedge, or stance" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "translation_budget" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "soft reading target" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert "The main takeaway is that X" in SEMANTIC_FULL_TRANSLATION_PROMPT
    assert SEMANTIC_FULL_TRANSLATION_PROMPT_VERSION == "semantic-full-translation-v7"
    assert SEMANTIC_FULL_TRANSLATION_CACHE_TASK == "screen_subtitle_semantic_full_translation_v7"


def test_attached_backchannel_chinese_is_compacted_without_erasing_responses():
    compact = ScreenSubtitleEditor._compact_attached_backchannel_translation

    assert compact("Yeah. This pattern spread quickly.", "对，这种模式迅速传播。") == "这种模式迅速传播。"
    assert compact("Right, the numbers changed.", "没错，数字发生了变化。") == "数字发生了变化。"
    assert compact("Exactly. That is the point.", "正是如此。这就是关键。") == "这就是关键。"
    assert compact("Yeah.", "对。") == "对。"
    assert compact("No. That is not true.", "不。事实并非如此。") == "不。事实并非如此。"
    assert compact("Wow. That changed everything.", "哇，这改变了一切。") == "哇，这改变了一切。"


def test_full_translation_em_dash_style_detector_ignores_lexical_hyphen():
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("盎格鲁-撒克逊传统") == []
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("——研究结论")
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("研究结论——")
    assert ScreenSubtitleEditor._full_translation_em_dash_findings("甲——乙——丙")


def test_full_translation_style_retry_only_retries_flagged_group_and_accepts_improvement():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "An ordinary statement."
    items[1].original = "The study found a clear result."
    groups = [_id_group(1, 0, [items[0]]), _id_group(2, 1, [items[1]])]
    calls = []

    def request(prompt, payload, cache_task, **kwargs):
        calls.append((cache_task, [entry["id"] for entry in payload]))
        if cache_task == "screen_subtitle_semantic_full_translation_v7":
            return {
                "groups": [
                    {
                        "id": 1,
                        "source_english": payload[0]["full_english"],
                        "full_translation": "这是一句普通陈述。",
                    },
                    {
                        "id": 2,
                        "source_english": payload[1]["full_english"],
                        "full_translation": "这项研究得出了明确结论——",
                    },
                ]
            }
        assert cache_task == "screen_subtitle_semantic_full_translation_style_retry_v1"
        assert payload[0]["current_translation"] == "这项研究得出了明确结论——"
        return {
            "groups": [
                {
                    "id": 2,
                    "source_english": payload[0]["full_english"],
                    "full_translation": "这项研究得出了明确结论。",
                }
            ]
        }

    with patch.object(editor, "_request_semantic_full_translation_chunk", side_effect=request):
        full_translations = editor._translate_semantic_group_full_translations(groups)

    assert calls == [
        ("screen_subtitle_semantic_full_translation_v7", [1, 2]),
        ("screen_subtitle_semantic_full_translation_style_retry_v1", [2]),
    ]
    assert full_translations == {1: "这是一句普通陈述。", 2: "这项研究得出了明确结论。"}
    assert editor._last_full_translation_style_retry_log == [
        {
            "semantic_group_id": "G0002",
            "cache_task": "screen_subtitle_semantic_full_translation_style_retry_v1",
            "original_translation": "这项研究得出了明确结论——",
            "candidate_translation": "这项研究得出了明确结论。",
            "original_style_findings": [{"code": "em_dash_at_translation_boundary", "em_dash_runs": 1}],
            "candidate_style_findings": [],
            "original_style_score": 3,
            "candidate_style_score": 0,
            "accepted": True,
            "decision": "accept_style_retry",
            "rejection_reasons": [],
        }
    ]
    assert [item.original for item in items] == ["An ordinary statement.", "The study found a clear result."]
    assert [item.subtitle_id for item in items] == ["S0001", "S0002"]


def test_full_translation_style_retry_keeps_original_when_candidate_loses_number_or_negation():
    editor = _id_editor()
    original = "该公司没有批准42份提案——"
    with patch.object(
        editor,
        "_request_semantic_full_translation_chunk",
        return_value={
            "groups": [
                {
                    "id": 1,
                    "source_english": "The company did not approve 42 proposals.",
                    "full_translation": "该公司批准了这些提案。",
                }
            ]
        },
    ):
        result = editor._retry_full_translations_for_em_dash_style(
            payload_by_id={
                1: {
                    "id": 1,
                    "full_english": "The company did not approve 42 proposals.",
                    "current_translation": original,
                }
            },
            full_translations={1: original},
        )

    assert result == {1: original}
    assert editor._last_full_translation_style_retry_log[-1]["decision"] == "keep_original"
    assert set(editor._last_full_translation_style_retry_log[-1]["rejection_reasons"]) == {
        "lost_number_anchor:42",
        "lost_negation_anchor:negation",
    }


def test_two_stage_translation_failure_does_not_fallback_to_single_stage():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2, translated="old-{index}"))

    with patch.object(editor, "_translate_semantic_group_full_translations", return_value={}), patch.object(
        editor,
        "_translate_semantic_subtitle_groups_single_stage",
        side_effect=AssertionError("single-stage fallback must not run"),
    ):
        result = editor._translate_semantic_subtitle_groups(items)

    assert [item.subtitle_id for item in result] == ["S0001", "S0002"]
    assert [item.translated for item in result] == ["old-1", "old-2"]


def test_missing_fixed_id_chinese_stops_at_translation_owner_with_provider_error():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2, translated=""))
    editor._semantic_allocation_request_failures = [
        {
            "task": "screen_subtitle_semantic_translation_allocation_v3",
            "error": "Request timed out.",
        }
    ]

    try:
        editor._validate_final_item_translation_ids(items)
        assert False, "missing fixed-ID Chinese must stop before authority artifacts"
    except RuntimeError as exc:
        message = str(exc)
        assert message.startswith("semantic_chinese_incomplete:")
        assert "S0001,S0002" in message
        assert "Request timed out." in message
        assert "authoritative_parent_chinese" not in message

    assert editor._translation_structure_errors[-1]["code"] == (
        "final_translation_id_mismatch"
    )
    assert editor._translation_structure_errors[-1]["missing_subtitle_ids"] == [
        "S0001",
        "S0002",
    ]


def test_semantic_allocation_request_retains_provider_failure_for_owner_error():
    editor = _id_editor()

    with patch.object(
        editor,
        "_request_semantic_translation_allocation_api_only",
        return_value=(None, "Error code: 500 - Internal server error"),
    ):
        result = editor._request_semantic_translation_allocation(
            "allocation prompt",
            [{"id": 1}],
        )

    assert result is None
    assert editor._semantic_allocation_request_failures == [
        {
            "task": "screen_subtitle_semantic_translation_allocation_v3",
            "error": "Error code: 500 - Internal server error",
        }
    ]


def test_allocation_retries_incomplete_chunk_by_single_group_without_lingering_errors():
    editor = _id_editor()
    editor.batch_num = 24
    editor.allocation_batch_size = 24
    items = editor._assign_global_subtitle_ids(_id_items(6))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 4)
    ]
    full_translations = {
        index: f"译文S{index * 2 - 1:04d}译文S{index * 2:04d}"
        for index in range(1, 4)
    }
    calls = []

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation",
        **kwargs,
    ):
        calls.append((cache_task, [entry["id"] for entry in payload]))
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "译文S0001"},
                            {"subtitle_id": "S0002", "zh": "译文S0002"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": part["subtitle_id"],
                            "zh": f"译文{part['subtitle_id']}",
                        }
                        for part in entry["subtitle_parts"]
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert calls == [
        ("screen_subtitle_semantic_translation_allocation_v3", [1, 2, 3]),
        ("screen_subtitle_semantic_translation_allocation_retry_v3", [1]),
        ("screen_subtitle_semantic_translation_allocation_retry_v3", [2]),
        ("screen_subtitle_semantic_translation_allocation_retry_v3", [3]),
    ]
    assert allocated == {
        1: {"S0001": "译文S0001", "S0002": "译文S0002"},
        2: {"S0003": "译文S0003", "S0004": "译文S0004"},
        3: {"S0005": "译文S0005", "S0006": "译文S0006"},
    }
    assert editor._translation_structure_errors == []


def test_allocation_concurrency_merges_out_of_order_batches_by_id():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(8))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 5)
    ]
    full_translations = {
        index: "".join(f"译文{item.subtitle_id}" for item in group["items"])
        for index, group in enumerate(groups, 1)
    }
    completions = []

    def request_api(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation",
        **_kwargs,
    ):
        ids = [entry["id"] for entry in payload]
        if ids == [1, 2]:
            time.sleep(0.05)
        completions.append(ids)
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {"subtitle_id": part["subtitle_id"], "zh": f"译文{part['subtitle_id']}"}
                            for part in entry["subtitle_parts"]
                        ],
                    }
                    for entry in reversed(payload)
                ]
            },
            "",
            [],
        )

    with patch.object(editor, "_request_semantic_translation_allocation_api_with_attempts", side_effect=request_api):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert completions[0] == [3, 4]
    assert allocated == {
        1: {"S0001": "译文S0001", "S0002": "译文S0002"},
        2: {"S0003": "译文S0003", "S0004": "译文S0004"},
        3: {"S0005": "译文S0005", "S0006": "译文S0006"},
        4: {"S0007": "译文S0007", "S0008": "译文S0008"},
    }
    assert [entry["batch_id"] for entry in editor._last_llm_raw_returns] == [1, 2]
    assert editor._translation_structure_errors == []


def test_allocation_concurrency_retries_one_failed_batch_without_dropping_completed_batches():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(8))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 5)
    ]
    full_translations = {
        index: "".join(f"译文{item.subtitle_id}" for item in group["items"])
        for index, group in enumerate(groups, 1)
    }
    retried = []

    def request_api(prompt, payload, cache_task="screen_subtitle_semantic_translation_allocation"):
        ids = [entry["id"] for entry in payload]
        if ids == [1, 2]:
            return None, "timeout", []
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {
                                "subtitle_id": part["subtitle_id"],
                                "zh": f"译文{part['subtitle_id']}",
                            }
                            for part in entry["subtitle_parts"]
                        ],
                    }
                    for entry in payload
                ]
            },
            "",
            [],
        )

    def retry_request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation_retry",
        **_kwargs,
    ):
        retried.append([entry["id"] for entry in payload])
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": part["subtitle_id"],
                            "zh": f"译文{part['subtitle_id']}",
                        }
                        for part in entry["subtitle_parts"]
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation_api_with_attempts", side_effect=request_api), patch.object(
        editor, "_request_semantic_translation_allocation", side_effect=retry_request
    ):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert retried == [[1], [2]]
    assert allocated == {
        1: {"S0001": "译文S0001", "S0002": "译文S0002"},
        2: {"S0003": "译文S0003", "S0004": "译文S0004"},
        3: {"S0005": "译文S0005", "S0006": "译文S0006"},
        4: {"S0007": "译文S0007", "S0008": "译文S0008"},
    }
    assert editor._translation_structure_errors == []


def test_allocation_concurrency_keeps_hit_only_context_for_cache_api_and_retry():
    editor = _id_editor()
    editor.allocation_batch_size = 1
    editor.allocation_max_concurrency = 2
    editor.article_context_data = {
        "summary": "Allocation context.",
        "technical_terms": [
            {
                "canonical_name": "AlphaTerm",
                "chinese_name": "甲术语",
                "aliases": [],
                "category": "term",
            },
            {
                "canonical_name": "BetaTerm",
                "chinese_name": "乙术语",
                "aliases": [],
                "category": "term",
            },
        ],
    }
    items = editor._assign_global_subtitle_ids(
        [
            ScreenSubtitleItem([1], "AlphaTerm starts.", "", 0, 1),
            ScreenSubtitleItem([2], "AlphaTerm continues.", "", 2, 3),
            ScreenSubtitleItem([3], "BetaTerm starts.", "", 4, 5),
            ScreenSubtitleItem([4], "BetaTerm continues.", "", 6, 7),
        ]
    )
    groups = [
        _id_group(1, 0, items[:2]),
        _id_group(2, 2, items[2:]),
    ]
    full_translations = {1: "甲组完整翻译", 2: "乙组完整翻译"}
    cache_load_prompts = []
    api_prompts = []
    cache_store_prompts = []
    retry_prompts = []

    def load_cache(prompt, payload, expected, **kwargs):
        cache_load_prompts.append((tuple(entry["id"] for entry in payload), prompt))
        return None

    def request_api(prompt, payload, **kwargs):
        ids = tuple(entry["id"] for entry in payload)
        api_prompts.append((ids, prompt))
        if ids == (1,):
            return None, "timeout", []
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {
                                "subtitle_id": part["subtitle_id"],
                                "zh": f"译文-{part['subtitle_id']}",
                            }
                            for part in entry["subtitle_parts"]
                        ],
                    }
                    for entry in payload
                ]
            },
            "",
            [],
        )

    def store_cache(prompt, payload, data, **kwargs):
        cache_store_prompts.append((tuple(entry["id"] for entry in payload), prompt))

    def retry_request(prompt, payload, **kwargs):
        retry_prompts.append((tuple(entry["id"] for entry in payload), prompt))
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": part["subtitle_id"],
                            "zh": f"重试-{part['subtitle_id']}",
                        }
                        for part in entry["subtitle_parts"]
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(
        editor,
        "_load_cached_allocation_batch",
        side_effect=load_cache,
    ), patch.object(
        editor,
        "_request_semantic_translation_allocation_api_with_attempts",
        side_effect=request_api,
    ), patch.object(
        editor,
        "_store_allocation_batch_cache",
        side_effect=store_cache,
    ), patch.object(
        editor,
        "_request_semantic_translation_allocation",
        side_effect=retry_request,
    ):
        allocated = editor._allocate_semantic_group_translations(
            groups,
            full_translations,
        )

    assert set(allocated) == {1, 2}
    prompt_records = [
        *cache_load_prompts,
        *api_prompts,
        *cache_store_prompts,
        *retry_prompts,
    ]
    assert prompt_records
    for ids, prompt in prompt_records:
        if ids == (1,):
            assert "AlphaTerm -> 甲术语" in prompt
            assert "BetaTerm -> 乙术语" not in prompt
        elif ids == (2,):
            assert "BetaTerm -> 乙术语" in prompt
            assert "AlphaTerm -> 甲术语" not in prompt
        else:
            raise AssertionError(f"unexpected allocation batch: {ids}")


def test_allocation_concurrency_records_duplicate_and_unknown_ids_after_retry_failure():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 1
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(4))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 3)
    ]
    full_translations = {1: "第一组完整译文", 2: "第二组完整译文"}

    def bad_response(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation",
        **_kwargs,
    ):
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "one"},
                        {"subtitle_id": "S0001", "zh": "duplicate"},
                        {"subtitle_id": "S9999", "zh": "unknown"},
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation_api_with_attempts", return_value=(bad_response("", []), "", [])), patch.object(
        editor, "_request_semantic_translation_allocation", side_effect=bad_response
    ):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated[1] == {"S0001": "one"}
    codes = _codes(editor)
    assert "translation_id_duplicate" in codes
    assert "translation_id_unknown" in codes
    assert "translation_group_cardinality_mismatch" in codes


def test_allocation_concurrency_uses_mixed_cache_hits_without_worker_cache_writes():
    editor = _id_editor()
    editor.batch_num = 2
    editor.allocation_batch_size = 2
    editor.allocation_max_concurrency = 2
    cached_payload = {
        "groups": [
            {
                "id": 1,
                "part_translations": [
                    {"subtitle_id": "S0001", "zh": "cached-1a"},
                    {"subtitle_id": "S0002", "zh": "cached-1b"},
                ],
            },
            {
                "id": 2,
                "part_translations": [
                    {"subtitle_id": "S0003", "zh": "cached-2a"},
                    {"subtitle_id": "S0004", "zh": "cached-2b"},
                ],
            },
        ]
    }
    class BatchOnlyQueueCache(_QueueCache):
        def get_llm_result(self, *args, **kwargs):
            if kwargs.get("task") == "screen_subtitle_semantic_translation_allocation_unit_v1":
                return None
            return super().get_llm_result(*args, **kwargs)

    editor.cache_manager = BatchOnlyQueueCache(
        [json.dumps(cached_payload, ensure_ascii=False), None]
    )
    items = editor._assign_global_subtitle_ids(_id_items(8))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 5)
    ]
    full_translations = {index: f"full-{index}" for index in range(1, 5)}

    def request_api(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation",
        **_kwargs,
    ):
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {
                                "subtitle_id": part["subtitle_id"],
                                "zh": f"api-{part['subtitle_id']}",
                            }
                            for part in entry["subtitle_parts"]
                        ],
                    }
                    for entry in payload
                ]
            },
            "",
            [{"attempt": 1, "elapsed_seconds": 0.0, "response": None, "error": None}],
        )

    with patch.object(editor, "_request_semantic_translation_allocation_api_with_attempts", side_effect=request_api):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated == {
        1: {"S0001": "cached-1a", "S0002": "cached-1b"},
        2: {"S0003": "cached-2a", "S0004": "cached-2b"},
        3: {"S0005": "api-S0005", "S0006": "api-S0006"},
        4: {"S0007": "api-S0007", "S0008": "api-S0008"},
    }
    assert editor._llm_cache_used is True
    assert len(editor.cache_manager.set_calls) >= 1
    assert set(editor.cache_manager.set_thread_ids) == {threading.get_ident()}
    assert editor._llm_cache_stats["screen_subtitle_semantic_translation_allocation_v3"] == {"hit": 1, "miss": 1}
    assert editor._allocation_runtime_stats["batch_size"] == 2
    assert editor._allocation_runtime_stats["batch_count"] == 2
    assert editor._allocation_runtime_stats["cached_batch_count"] == 1
    assert editor._allocation_runtime_stats["pending_batch_count"] == 1
    assert editor._allocation_runtime_stats["actual_max_workers"] == 1
    assert editor._translation_structure_errors == []


def test_chinese_polish_rewrites_only_fixed_group_chinese_by_id():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    item = editor._assign_global_subtitle_ids(_id_items(1))[0]
    item.original = "The system adapts to feedback."
    groups = [_id_group(1, 0, [item])]
    full_translations = {1: "系统会根据人类反馈不断调整。"}
    allocations = {1: {"S0001": "系统将"}}

    def request(prompt, payload, cache_task, **kwargs):
        assert cache_task == "screen_subtitle_semantic_chinese_polish_v3"
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": entry["subtitle_parts"][0]["subtitle_id"],
                            "zh": "系统会根据人类反馈不断调整。",
                        }
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert polished == {1: {"S0001": "系统会根据人类反馈不断调整。"}}
    assert item.original == "The system adapts to feedback."
    assert editor._chinese_polish_log[-1]["decision"] == "applied"


def test_chinese_polish_skips_natural_groups_without_a_model_request():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    item = editor._assign_global_subtitle_ids(_id_items(1))[0]
    item.original = "The system adapts to feedback."
    groups = [_id_group(1, 0, [item])]
    full_translations = {1: "系统会根据人类反馈不断调整。"}
    allocations = {1: {"S0001": "系统会根据人类反馈不断调整。"}}

    with patch.object(editor, "_request_semantic_translation_allocation") as request:
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert polished == allocations
    assert not request.called


def test_chinese_polish_selects_complex_comparison_group_by_fixed_ids():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    items = editor._assign_global_subtitle_ids(_id_items(4))
    items[0].original = "They compared leading models"
    items[1].original = "against writing from The Economist,"
    items[2].original = "CNN, The New York Times,"
    items[3].original = "and novels published from 1950 to 2022."
    groups = [_id_group(1, 0, items)]
    full_translations = {
        1: "他们将顶尖模型的输出，与《经济学人》、CNN、《纽约时报》以及1950年至2022年的畅销小说进行比较。"
    }
    allocations = {
        1: {
            "S0001": "他们比较了顶尖模型——",
            "S0002": "与《经济学人》的写作，",
            "S0003": "CNN和《纽约时报》，",
            "S0004": "以及1950至2022年的畅销小说。",
        }
    }

    def request(prompt, payload, cache_task, **kwargs):
        assert cache_task == "screen_subtitle_semantic_chinese_polish_v3"
        assert payload[0]["translation_context_version"] == (
            "semantic-full-translation-context-v1"
        )
        assert payload[0]["translation_context"]["previous"] == []
        assert payload[0]["translation_context"]["next"] == []
        assert payload[0]["subtitle_parts"][0]["target_zh_chars"] >= 4
        return {
            "groups": [{
                "id": 1,
                "part_translations": [
                    {"subtitle_id": "S0001", "zh": "他们将顶尖模型的输出，"},
                    {"subtitle_id": "S0002", "zh": "与《经济学人》的写作进行比较，"},
                    {"subtitle_id": "S0003", "zh": "对象还包括CNN和《纽约时报》，"},
                    {"subtitle_id": "S0004", "zh": "以及1950至2022年的畅销小说。"},
                ],
            }]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request) as call:
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert call.called
    assert polished[1]["S0002"] == "与《经济学人》的写作进行比较，"
    assert any(
        "complex_enumeration_or_comparison_allocation" in item.get("issue_codes", [])
        for item in editor._chinese_polish_log
        if item.get("decision") == "selected"
    )
    applied = [item for item in editor._chinese_polish_log if item.get("decision") == "applied"]
    assert applied[-1]["quality_comparison"]["require_high_confidence_fix"] is False


def test_cross_subtitle_predicate_break_triggers_group_polish_by_fixed_ids():
    editor = _id_editor()
    editor.enable_chinese_polish = True
    items = [
        ScreenSubtitleItem([1], "A recent study found that the AI models", "", 0, 1),
        ScreenSubtitleItem([2], "currently drafting over a third of new websites", "", 2, 3),
        ScreenSubtitleItem([3], "have stopped using those words.", "", 4, 5),
    ]
    items = editor._assign_global_subtitle_ids(items)
    groups = [_id_group(1, 0, items)]
    full_translations = {
        1: "一项分析了120万个词的最新研究发现，如今超过三分之一的新网站由AI模型撰写，而这些模型已不再使用那些词。"
    }
    allocations = {
        1: {
            "S0001": "最近一项分析120万单词的研究发现",
            "S0002": "目前正在撰写超过三分之一新网站的AI模型",
            "S0003": "突然不再使用那些词了。",
        }
    }
    frozen_before = [
        (item.original, item.subtitle_id, item.word_start, item.word_end)
        for item in items
    ]

    entry = {
        "id": 1,
        "full_english": " ".join(item.original for item in items),
        "full_translation": full_translations[1],
        "subtitle_parts": [
            {"subtitle_id": item.subtitle_id, "english": item.original}
            for item in items
        ],
    }
    validation = editor._validate_group_chinese_allocation(entry, allocations[1])
    assert "cross_subtitle_predicate_break" in validation["issue_codes"]

    def request(prompt, payload, cache_task, **kwargs):
        assert cache_task == "screen_subtitle_semantic_chinese_polish_v3"
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "一项分析了120万个词的最新研究发现，"},
                        {"subtitle_id": "S0002", "zh": "如今超过三分之一的新网站由AI模型撰写，"},
                        {"subtitle_id": "S0003", "zh": "而这些模型已不再使用那些词。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request) as call:
        polished = editor._polish_semantic_group_translations(
            groups, full_translations, allocations
        )

    assert call.called
    assert polished[1]["S0002"] == "如今超过三分之一的新网站由AI模型撰写，"
    assert [
        (item.original, item.subtitle_id, item.word_start, item.word_end)
        for item in items
    ] == frozen_before
    assert editor._chinese_polish_log[-1]["decision"] == "applied"


def test_cross_subtitle_predicate_break_does_not_flag_normal_chinese_continuation():
    issues = ScreenSubtitleEditor._detect_cross_subtitle_predicate_breaks(
        ["S0001", "S0002", "S0003"],
        [
            "一项最新研究发现，",
            "如今超过三分之一的新网站由AI模型撰写，",
            "而这些模型已不再使用那些词。",
        ],
    )

    assert issues == []


def test_semantic_loss_recognizes_bingfei_as_negation():
    assert not ScreenSubtitleEditor._has_core_semantic_loss(
        "再看最新的人口普查数据和美联储研究，他并非个例。",
        "再看最新的人口普查数据和美联储研究，他并非个例。",
        "And looking at the latest census data and Federal Reserve research, he is not an outlier.",
    )


def test_sentence_final_shide_is_not_a_dangling_chinese_fragment():
    assert not ScreenSubtitleEditor._is_bad_chinese_fragment(
        "但到2025年，全职自雇人数创下百年新高。是的。"
    )


def test_allocation_concurrency_preserves_400_plus_subtitle_ids_without_drift():
    editor = _id_editor()
    editor.batch_num = 24
    editor.allocation_batch_size = 24
    editor.allocation_max_concurrency = 2
    items = editor._assign_global_subtitle_ids(_id_items(432))
    groups = [
        _id_group(index, (index - 1) * 2, items[(index - 1) * 2 : index * 2])
        for index in range(1, 217)
    ]
    full_translations = {
        index: "".join(f"译文{item.subtitle_id}" for item in group["items"])
        for index, group in enumerate(groups, 1)
    }

    def request_api(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation",
        **_kwargs,
    ):
        return (
            {
                "groups": [
                    {
                        "id": entry["id"],
                        "part_translations": [
                            {
                                "subtitle_id": part["subtitle_id"],
                                "zh": f"译文{part['subtitle_id']}",
                            }
                            for part in entry["subtitle_parts"]
                        ],
                    }
                    for entry in reversed(payload)
                ]
            },
            "",
            [],
        )

    with patch.object(editor, "_request_semantic_translation_allocation_api_with_attempts", side_effect=request_api):
        translations = editor._allocate_semantic_group_translations(groups, full_translations)
    applied = editor._apply_semantic_group_translations(items, groups, translations)

    assert [item.subtitle_id for item in applied] == [f"S{index:04d}" for index in range(1, 433)]
    assert [item.translated for item in applied] == [f"译文S{index:04d}" for index in range(1, 433)]
    assert editor._translation_structure_errors == []


def test_allocation_quality_retries_information_leaked_to_previous_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Alice arrived."
    items[1].original = "Bob signed 42 contracts."
    groups = [_id_group(1, 0, items)]
    full_translations = {1: "爱丽丝到了。鲍勃签了42份合同。"}
    calls = []

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation_v3",
        **kwargs,
    ):
        calls.append(cache_task)
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "鲍勃签了42份合同。"},
                            {"subtitle_id": "S0002", "zh": "爱丽丝到了。"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "爱丽丝到了。"},
                        {"subtitle_id": "S0002", "zh": "鲍勃签了42份合同。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated[1] == {"S0001": "爱丽丝到了。", "S0002": "鲍勃签了42份合同。"}
    assert calls == [
        "screen_subtitle_semantic_translation_allocation_v3",
        "screen_subtitle_semantic_translation_allocation_retry_v3",
    ]
    assert any("number_allocation_mismatch" in item["issue_codes"] for item in editor._last_allocation_validation)
    assert editor._last_allocation_retry_log[-1]["success"] is True
    assert editor._translation_structure_errors == []


def test_malformed_optional_quality_retry_keeps_valid_original_allocation_local():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "The value will not be swallowed up"
    items[1].original = "by Silicon Valley tech giants."
    group = _id_group(180, 0, items)
    full_translations = {
        180: "这些价值不会只被硅谷的少数科技巨头吞掉。",
    }

    def request(prompt, payload, cache_task, **kwargs):
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [{
                    "id": 180,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "这些价值不会只被科技巨头吞掉"},
                        {"subtitle_id": "S0002", "zh": "尤其是硅谷的。"},
                    ],
                }]
            }
        return {
            "groups": [{
                "id": 1,
                "part_translations": [
                    {"subtitle_id": "S0001", "zh": "错误重试一"},
                    {"subtitle_id": "S0002", "zh": "错误重试二"},
                ],
            }]
        }

    with patch.object(
        editor,
        "_request_semantic_translation_allocation",
        side_effect=request,
    ):
        allocated = editor._allocate_semantic_group_translations(
            [group],
            full_translations,
        )

    assert allocated[180] == {
        "S0001": "这些价值不会只被科技巨头吞掉",
        "S0002": "尤其是硅谷的。",
    }
    assert editor._translation_structure_errors == []
    attempts = [
        record
        for record in editor._last_allocation_validation
        if record.get("record_type") == "allocation_structure_attempt"
    ]
    assert attempts[-1]["stage"] == "quality_retry"
    assert attempts[-1]["expected_semantic_group_ids"] == [180]
    assert editor._last_allocation_retry_log[-1]["success"] is False
    assert editor._last_allocation_unresolved[-1]["reason"] == "retry_structure_failed"


def test_allocation_quality_retries_displaced_main_clause_before_causal_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = (
        "engineering a lightweight engine that somehow wins the exact same race,"
    )
    items[1].original = "just because it is not carrying all that weight."
    group = _id_group(1, 0, items)
    full_translations = {
        1: "打造一台轻量发动机，它居然能赢下同一场比赛，只因不用背负那份重量。",
    }
    calls = []

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation_v3",
        **kwargs,
    ):
        calls.append(cache_task)
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "打造一台轻量发动机，"},
                            {
                                "subtitle_id": "S0002",
                                "zh": "它居然能赢下同一场比赛，只因不用背负那份重量。",
                            },
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {
                            "subtitle_id": "S0001",
                            "zh": "打造一台轻量发动机，它居然能赢下同一场比赛，",
                        },
                        {"subtitle_id": "S0002", "zh": "只因不用背负那份重量。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations([group], full_translations)

    assert allocated[1] == {
        "S0001": "打造一台轻量发动机，它居然能赢下同一场比赛，",
        "S0002": "只因不用背负那份重量。",
    }
    assert calls == [
        "screen_subtitle_semantic_translation_allocation_v3",
        "screen_subtitle_semantic_translation_allocation_retry_v3",
    ]
    assert any(
        "cross_id_semantic_leakage" in validation["issue_codes"]
        for validation in editor._last_allocation_validation
    )
    assert editor._last_allocation_retry_log[-1]["success"] is True


def test_allocation_quality_retries_orphaned_bare_preposition_prefix():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Yeah. And that is despite the fact"
    items[1].original = "that the economy is large."
    group = _id_group(1, 0, items)
    full_translations = {1: "是啊。即便如此，经济规模很大也成立。"}
    calls = []

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation_v3",
        **kwargs,
    ):
        calls.append(cache_task)
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "是啊。这一点甚至是在"},
                            {"subtitle_id": "S0002", "zh": "经济规模很大也成立。"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "是啊。即便如此，"},
                        {"subtitle_id": "S0002", "zh": "经济规模很大也成立。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations([group], full_translations)

    assert allocated[1] == {
        "S0001": "是啊。即便如此，",
        "S0002": "经济规模很大也成立。",
    }
    assert calls == [
        "screen_subtitle_semantic_translation_allocation_v3",
        "screen_subtitle_semantic_translation_allocation_fragment_retry_v1",
    ]
    assert any(
        issue.get("subtitle_id") == "S0001"
        and issue.get("code") == "unnatural_chinese_fragment"
        for validation in editor._last_allocation_validation
        for issue in validation["issues"]
    )
    assert editor._last_allocation_retry_log[-1]["success"] is True


def test_allocation_quality_rejects_adjacent_core_duplication():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Alice arrived."
    items[1].original = "Bob left."
    entry = {
        "id": 1,
        "full_translation": "爱丽丝到了。鲍勃离开了。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": items[0].original},
            {"subtitle_id": "S0002", "english": items[1].original},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "鲍勃离开了。", "S0002": "鲍勃离开了。"},
    )

    assert not validation["valid"]
    assert "adjacent_chinese_semantic_duplication" in validation["issue_codes"]


def test_allocation_quality_rejects_adjacent_long_common_phrase_duplication():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "身边的人究竟是爱真实的我们，还是只是爱上了我们雇来替我们说话的算法？",
        "subtitle_parts": [
            {
                "subtitle_id": "S0001",
                "english": "if the people in our lives actually love us for who we are, or if they're",
            },
            {
                "subtitle_id": "S0002",
                "english": "just in love with the algorithm we hired to speak for us?",
            },
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "身边的人究竟是爱真实的我们，还是只是爱上了那个我们雇来替我们说话的算法呢",
            "S0002": "只是爱上了我们雇来替我们说话的算法吗？",
        },
    )

    assert not validation["valid"]
    assert "adjacent_chinese_semantic_duplication" in validation["issue_codes"]
    assert any(
        issue.get("reason") == "adjacent_long_common_phrase"
        for issue in validation["issues"]
    )


def test_allocation_quality_detects_negation_misplacement():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "方案可行。但它不能扩展。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "The plan works."},
            {"subtitle_id": "S0002", "english": "But it does not scale."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "它不能扩展。", "S0002": "方案可行。"},
    )

    assert not validation["valid"]
    assert "negation_allocation_mismatch" in validation["issue_codes"]


def test_allocation_quality_allows_negation_with_adjacent_predicate_completion():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "把工作当作巨大方程，难道不会剥夺我们的人性吗？",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "doesn't treating your life's work like"},
            {"subtitle_id": "S0002", "english": "a giant equation strip away our humanity?"},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "把工作当作",
            "S0002": "巨大方程，难道不会剥夺我们的人性吗？",
        },
    )

    assert validation["valid"]
    assert "negation_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_accepts_common_chinese_negation_equivalents():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "你无需担心。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "You do not need to worry."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "你无需担心。"},
    )

    assert validation["valid"]
    assert "negation_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_accepts_entity_spacing_equivalent():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "OpenAI released the model.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Open AI released the model."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "OpenAI released the model."},
    )

    assert validation["valid"]
    assert "entity_allocation_mismatch" not in validation["issue_codes"]
    assert "cross_id_semantic_leakage" not in validation["issue_codes"]


def test_allocation_quality_accepts_chinese_number_equivalents():
    editor = _id_editor()
    percent_entry = {
        "id": 1,
        "full_translation": "哦，百分之百。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Oh, 100%."},
        ],
    }
    percent_validation = editor._validate_group_chinese_allocation(
        percent_entry,
        {"S0001": "哦，百分之百。"},
    )

    hours_entry = {
        "id": 2,
        "full_translation": "这本书叫《八万小时》。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "The book is called 80 000 Hours."},
        ],
    }
    hours_validation = editor._validate_group_chinese_allocation(
        hours_entry,
        {"S0001": "这本书叫《八万小时》。"},
    )
    million_entry = {
        "id": 3,
        "full_translation": "拥有一千万并不会让你更快乐。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Having 10 million does not make you happier."},
        ],
    }
    million_validation = editor._validate_group_chinese_allocation(
        million_entry,
        {"S0001": "拥有一千万并不会让你更快乐。"},
    )
    blue_collar_entry = {
        "id": 5,
        "full_translation": "中国经济中蓝领工人的数量达到了4亿人。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "China has 400 million blue-collar workers."},
        ],
    }
    blue_collar_validation = editor._validate_group_chinese_allocation(
        blue_collar_entry,
        {"S0001": "中国经济中蓝领工人的数量达到了4亿人。"},
    )
    raised_entry = {
        "id": 6,
        "full_translation": "他们募集了579亿人民币。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "They raised 57.9 billion yuan."},
        ],
    }
    raised_validation = editor._validate_group_chinese_allocation(
        raised_entry,
        {"S0001": "他们募集了579亿人民币。"},
    )
    usd_entry = {
        "id": 7,
        "full_translation": "大约是86亿美元。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "That's about 8.6 billion U S."},
        ],
    }
    usd_validation = editor._validate_group_chinese_allocation(
        usd_entry,
        {"S0001": "大约是86亿美元。"},
    )
    decade_entry = {
        "id": 8,
        "full_translation": "他在21世纪初转向健美。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "He pivoted to bodybuilding in the early 2000 s."},
        ],
    }
    decade_validation = editor._validate_group_chinese_allocation(
        decade_entry,
        {"S0001": "他在21世纪初转向健美。"},
    )
    economists_entry = {
        "id": 4,
        "full_translation": "那两百位经济学家发出了警告。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Those 200 economists issued a warning."},
        ],
    }
    economists_validation = editor._validate_group_chinese_allocation(
        economists_entry,
        {"S0001": "那两百位经济学家发出了警告。"},
    )

    assert percent_validation["valid"]
    assert "number_allocation_mismatch" not in percent_validation["issue_codes"]
    assert hours_validation["valid"]
    assert "number_allocation_mismatch" not in hours_validation["issue_codes"]
    assert million_validation["valid"]
    assert "number_allocation_mismatch" not in million_validation["issue_codes"]
    assert blue_collar_validation["valid"]
    assert "number_allocation_mismatch" not in blue_collar_validation["issue_codes"]
    assert raised_validation["valid"]
    assert "number_allocation_mismatch" not in raised_validation["issue_codes"]
    assert usd_validation["valid"]
    assert "number_allocation_mismatch" not in usd_validation["issue_codes"]
    assert decade_validation["valid"]
    assert "number_allocation_mismatch" not in decade_validation["issue_codes"]
    assert economists_validation["valid"]
    assert "number_allocation_mismatch" not in economists_validation["issue_codes"]


def test_allocation_quality_accepts_decimal_wan_number_equivalent():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "salary is about 7.7万美元。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "salary is about 77 000 dollars."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {"S0001": "salary is about 7.7万美元。"},
    )

    assert validation["valid"]
    assert "number_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_allows_adjacent_number_when_target_line_is_not_degraded():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "You save lives, about 20 times more.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "you save about 20 times more lives"},
            {"subtitle_id": "S0002", "english": "than the baseline."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "you save lives,",
            "S0002": "about 20 times more than the baseline.",
        },
    )

    assert validation["valid"]
    assert "number_allocation_mismatch" not in validation["issue_codes"]


def test_allocation_quality_rejects_adjacent_number_when_target_line_is_empty():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "You save lives, about 20 times more.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "you save about 20 times more lives"},
            {"subtitle_id": "S0002", "english": "than the baseline."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "",
            "S0002": "you save lives, about 20 times more than the baseline.",
        },
    )

    assert not validation["valid"]
    assert "number_allocation_mismatch" in validation["issue_codes"]


def test_allocation_quality_accepts_natural_subtitle_half_sentence():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "她指出，做好事和追随热情并不意味着你必须发誓过贫穷的生活。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "She points out that doing good and following your passion doesn't mean"},
            {"subtitle_id": "S0002", "english": "you have to take a vow of poverty."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "她指出，做好事和追随热情并不意味着",
            "S0002": "你必须发誓过贫穷的生活。",
        },
    )

    assert validation["valid"]
    assert "unnatural_chinese_fragment" not in validation["issue_codes"]


def test_allocation_retry_rejects_quality_regression_before_writeback():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(3))
    items[0].original = "Alice arrived."
    items[1].original = "Bob signed 42 contracts."
    items[2].original = "Carol approved the long budget plan."
    groups = [_id_group(1, 0, items)]
    full_translations = {
        1: "爱丽丝到了。鲍勃签了42份合同。卡罗尔批准了这份长期预算计划。",
    }

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation_v3",
        **kwargs,
    ):
        if cache_task == "screen_subtitle_semantic_translation_allocation_v3":
            return {
                "groups": [
                    {
                        "id": 1,
                        "part_translations": [
                            {"subtitle_id": "S0001", "zh": "爱丽丝到了。鲍勃签了42份合同。"},
                            {"subtitle_id": "S0002", "zh": "鲍勃签了合同。"},
                            {"subtitle_id": "S0003", "zh": "卡罗尔批准了这份长期预算计划。"},
                        ],
                    }
                ]
            }
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0001", "zh": "爱丽丝到了。"},
                        {"subtitle_id": "S0002", "zh": "鲍勃签了42份合同。"},
                        {"subtitle_id": "S0003", "zh": "卡罗尔批准预算。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    assert allocated[1]["S0003"] == "卡罗尔批准了这份长期预算计划。"
    assert editor._last_allocation_retry_log[-1]["success"] is False
    assert editor._last_allocation_unresolved[-1]["reason"] == "retry_rejected_due_to_quality_regression"
    assert editor._last_allocation_retry_log[-1]["original_allocation"]
    assert editor._last_allocation_retry_log[-1]["retry_allocation"]
    assert editor._last_allocation_retry_log[-1]["quality_comparison"]["decision"] == "keep_original"


def test_compare_allocation_candidates_accepts_strict_improvement_only():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "Alice arrived. Bob signed 42 contracts.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice arrived."},
            {"subtitle_id": "S0002", "english": "Bob signed 42 contracts."},
        ],
    }
    original = {"S0001": "Bob signed 42 contracts.", "S0002": "Alice arrived."}
    retry = {"S0001": "Alice arrived.", "S0002": "Bob signed 42 contracts."}
    original_validation = editor._validate_group_chinese_allocation(entry, original)
    retry_validation = editor._validate_group_chinese_allocation(entry, retry)

    comparison = editor._compare_allocation_candidates(
        original_allocation=original,
        retry_allocation=retry,
        group_context=entry,
        original_validation=original_validation,
        retry_validation=retry_validation,
    )

    assert comparison["accepted"]
    assert comparison["decision"] == "accept_retry"
    assert "number_allocation_mismatch" in comparison["fixed_issue_codes"]
    assert comparison["new_issue_codes"] == []


def test_compare_allocation_candidates_rejects_new_high_confidence_issue():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "Alice arrived. Bob signed 42 contracts.",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice arrived."},
            {"subtitle_id": "S0002", "english": "Bob signed 42 contracts."},
        ],
    }
    original = {"S0001": "Alice arrived.", "S0002": "Bob signed 42 contracts."}
    retry = {"S0001": "Bob signed 42 contracts.", "S0002": "Alice arrived."}
    original_validation = editor._validate_group_chinese_allocation(entry, original)
    retry_validation = editor._validate_group_chinese_allocation(entry, retry)

    comparison = editor._compare_allocation_candidates(
        original_allocation=original,
        retry_allocation=retry,
        group_context=entry,
        original_validation=original_validation,
        retry_validation=retry_validation,
    )

    assert not comparison["accepted"]
    assert comparison["decision"] == "keep_original"
    assert "new_high_confidence_issue" in comparison["reasons"]
    assert "number_allocation_mismatch" in comparison["new_issue_codes"]


def test_cross_id_leakage_requires_target_id_to_be_degraded():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "爱丽丝说明了背景。接着引用了Alice的原话。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice explained the context."},
            {"subtitle_id": "S0002", "english": "Then they quoted her exact words."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "她说明了背景。",
            "S0002": "接着引用了Alice的原话。",
        },
    )

    assert validation["valid"]
    assert "cross_id_semantic_leakage" not in validation["issue_codes"]


def test_cross_id_leakage_flags_when_target_id_is_consumed_and_empty():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "Alice说明了背景。下一句继续展开。",
        "subtitle_parts": [
            {"subtitle_id": "S0001", "english": "Alice explained the context."},
            {"subtitle_id": "S0002", "english": "The next sentence continued."},
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0001": "",
            "S0002": "Alice说明了背景。下一句继续展开。",
        },
    )

    assert not validation["valid"]
    assert "cross_id_semantic_leakage" in validation["issue_codes"]


def test_cross_id_relation_marker_cannot_move_to_previous_question_id():
    editor = _id_editor()
    entry = {
        "id": 12,
        "full_translation": "当经济标尺不再像尺子，而像球门柱时，会发生什么。",
        "subtitle_parts": [
            {"subtitle_id": "S0015", "english": "And what actually happens"},
            {
                "subtitle_id": "S0016",
                "english": "when an economic yardstick stops acting like a ruler and starts acting like a goalpost.",
            },
        ],
    }

    validation = editor._validate_group_chinese_allocation(
        entry,
        {
            "S0015": "当经济标尺不再像尺子",
            "S0016": "而像球门柱时，会发生什么。",
        },
    )

    assert not validation["valid"]
    assert "cross_id_semantic_leakage" in validation["issue_codes"]
    assert any(
        issue.get("reason") == "subordinate_relation_marker_moved_to_previous_id"
        for issue in validation["issues"]
    )


def test_allocation_quality_keeps_out_of_order_return_by_subtitle_id():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "The plan works."
    items[1].original = "It scales."
    groups = [_id_group(1, 0, items)]
    full_translations = {1: "方案可行。它可以扩展。"}

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation_v3",
        **kwargs,
    ):
        return {
            "groups": [
                {
                    "id": 1,
                    "part_translations": [
                        {"subtitle_id": "S0002", "zh": "它可以扩展。"},
                        {"subtitle_id": "S0001", "zh": "方案可行。"},
                    ],
                }
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    applied = editor._apply_semantic_group_translations(items, groups, allocated)
    assert [item.translated for item in applied] == ["方案可行。", "它可以扩展。"]
    assert editor._translation_structure_errors == []


def test_allocation_quality_failed_group_does_not_shift_following_100_ids():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(101))
    items[0].original = "It does not work."
    items[1].original = "It is still broken."
    groups = [
        _id_group(1, 0, items[:2]),
        *[_id_group(index, index, [items[index]]) for index in range(2, 101)],
    ]
    full_translations = {1: "它不能工作，问题仍未解决。", **{index: f"中文{index}" for index in range(2, 101)}}

    def request(
        prompt,
        payload,
        cache_task="screen_subtitle_semantic_translation_allocation_v3",
        **kwargs,
    ):
        return {
            "groups": [
                {
                    "id": entry["id"],
                    "part_translations": [
                        {
                            "subtitle_id": part["subtitle_id"],
                            "zh": "" if entry["id"] == 1 else f"中文{entry['id']}",
                        }
                        for part in entry["subtitle_parts"]
                    ],
                }
                for entry in payload
            ]
        }

    with patch.object(editor, "_request_semantic_translation_allocation", side_effect=request):
        allocated = editor._allocate_semantic_group_translations(groups, full_translations)

    applied = editor._apply_semantic_group_translations(items, groups, allocated)
    assert [item.subtitle_id for item in applied] == [f"S{index:04d}" for index in range(1, 102)]
    assert applied[100].translated == "中文100"
    assert editor._last_allocation_unresolved


def test_compression_quality_regression_restores_previous_group_allocation():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(2))
    items[0].original = "Alice arrived."
    items[1].original = "Bob left."
    group = _id_group(1, 0, items)
    editor._last_semantic_full_translations = {1: "爱丽丝到了。鲍勃离开了。"}
    before = [
        ASRDataSeg("Alice arrived.", 0, 1000, "爱丽丝到了。"),
        ASRDataSeg("Bob left.", 1000, 2000, "鲍勃离开了。"),
    ]
    after = [
        ASRDataSeg("Alice arrived.", 0, 1000, "鲍勃离开了。"),
        ASRDataSeg("Bob left.", 1000, 2000, "鲍勃离开了。"),
    ]
    for index, seg in enumerate(before + after):
        seg.subtitle_id = f"S{index % 2 + 1:04d}"

    restored = editor._restore_invalid_postprocess_allocations(
        before_segments=before,
        after_segments=after,
        semantic_groups=[group],
        subtitle_items=items,
    )

    assert [seg.translated_text for seg in restored] == ["爱丽丝到了。", "鲍勃离开了。"]
    assert editor._last_allocation_unresolved[-1]["reason"] == "postprocess_allocation_quality_regression_restored"


def test_speed_compression_cannot_accept_number_omission_for_shorter_chinese():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(1))
    items[0].original = "Alice successfully reached the annual sales target in 2024."
    group = _id_group(1, 0, items)
    full_translation = "爱丽丝在2024年成功达成了年度销售目标。"
    editor._last_semantic_full_translations = {1: full_translation}
    before = [
        ASRDataSeg(items[0].original, 0, 1000, full_translation),
    ]
    after = [
        ASRDataSeg(items[0].original, 0, 1000, "爱丽丝达成销售目标。"),
    ]
    before[0].subtitle_id = "S0001"
    after[0].subtitle_id = "S0001"

    restored = editor._restore_invalid_postprocess_allocations(
        before_segments=before,
        after_segments=after,
        semantic_groups=[group],
        subtitle_items=items,
    )

    assert restored[0].translated_text == full_translation
    comparison = editor._last_allocation_unresolved[-1]["candidate_comparison"]
    assert comparison["speed_improved"] is True
    assert "new_high_confidence_issue" in comparison["reasons"]


def test_id_bound_candidate_decision_never_accepts_invalid_candidate():
    editor = _id_editor()
    entry = {
        "id": 1,
        "full_translation": "爱丽丝到了。",
        "subtitle_parts": [{"subtitle_id": "S0001", "english": "Alice arrived."}],
    }
    allocation = {"S0001": "爱丽丝到了。"}
    decision = editor._decide_id_bound_allocation_candidate(
        original_allocation=allocation,
        candidate_allocation=allocation,
        group_context=entry,
        original_validation={"valid": True, "issue_codes": []},
        candidate_validation={
            "valid": False,
            "issue_codes": ["translation_group_cardinality_mismatch"],
        },
        candidate_source="test",
        require_high_confidence_fix=False,
    )

    assert not decision["accepted"]
    assert decision["decision"] == "keep_original"
    assert decision["candidate_source"] == "test"


def test_editor_review_points_only_include_long_split_allocation_mismatch():
    editor = _id_editor()
    segments = []
    for index in range(1, 5):
        seg = ASRDataSeg(
            text=f"English {index}",
            start_time=index * 1000,
            end_time=index * 1000 + 800,
            translated_text=f"中文{index}",
        )
        seg.subtitle_id = f"S{index:04d}"
        segments.append(seg)

    editor._last_allocation_unresolved = [
        {
            "semantic_group_id": "G0001",
            "reason": "retry_quality_failed",
            "issue_codes": ["number_allocation_mismatch"],
            "full_english": "Then in the 2000 s they joined the World Trade Organisation.",
            "full_translation": "然后，在21世纪初，中国加入了世界贸易组织。",
            "allocation": {"S0001": "然后，在21世纪初，", "S0002": "中国加入了世界贸易组织。"},
        },
        {
            "semantic_group_id": "G0002",
            "reason": "retry_quality_failed",
            "issue_codes": ["unnatural_chinese_fragment"],
            "full_english": "Short answer.",
            "full_translation": "短回答。",
            "allocation": {"S0003": "短回答。"},
        },
    ]

    points = editor._editor_review_points(segments)
    assert len(points) == 1
    assert points[0]["subtitle_ids"] == ["S0001", "S0002"]
    assert points[0]["end_ms"] == segments[1].end_time
    srt = editor._review_points_to_srt(points)
    assert "[QA] S0001-S0002" in srt
    assert "G0001" in srt
    assert "S0001 EN" in srt
    assert "S0002 EN" in srt
    assert "S0003" not in srt


def test_empty_middle_translation_keeps_its_own_id_slot():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(3))
    group = _id_group(1, 0, items)

    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": ""},
            {"subtitle_id": "S0003", "zh": "zh-S0003"},
        ],
    )
    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})
    try:
        editor._validate_final_item_translation_ids(applied)
        assert False, "empty fixed-ID Chinese must block before authority artifacts"
    except RuntimeError as exc:
        assert str(exc).startswith("semantic_chinese_incomplete:")
        assert "S0002" in str(exc)

    assert [item.subtitle_id for item in applied] == ["S0001", "S0002", "S0003"]
    assert applied[1].translated == ""
    assert applied[2].translated == "zh-S0003"
    final_errors = [
        issue for issue in editor._translation_structure_errors
        if issue["code"] == "final_translation_id_mismatch"
    ]
    assert final_errors and final_errors[0]["missing_subtitle_ids"] == ["S0002"]


def test_numeric_only_subtitle_keeps_semantic_group_id_slot():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(
        [
            ScreenSubtitleItem(
                original="Imports rose sharply.",
                translated="",
                source_ids=[1],
                word_start=0,
                word_end=2,
            ),
            ScreenSubtitleItem(
                original="70%.",
                translated="",
                source_ids=[2],
                word_start=3,
                word_end=3,
            ),
            ScreenSubtitleItem(
                original="That is a wild jump.",
                translated="",
                source_ids=[3],
                word_start=4,
                word_end=8,
            ),
        ]
    )

    groups = editor._semantic_translation_groups(items)
    grouped_ids = [
        subtitle_id
        for group in groups
        for subtitle_id in editor._group_expected_subtitle_ids(group)
    ]

    assert grouped_ids == ["S0001", "S0002", "S0003"]
    assert any(group["items"][0].original == "70%." for group in groups)


def test_failed_group_does_not_shift_following_100_subtitles():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(104))
    first = _id_group(1, 0, items[:4])
    tail = _id_group(2, 4, items[4:])
    first_translations = editor._parse_id_bound_translations(
        first,
        editor._group_expected_subtitle_ids(first),
        [
            {"subtitle_id": "S0001", "zh": "zh-S0001"},
            {"subtitle_id": "S0002", "zh": "zh-S0002"},
            {"subtitle_id": "S0004", "zh": "zh-S0004"},
        ],
    )
    tail_translations = editor._parse_id_bound_translations(
        tail,
        editor._group_expected_subtitle_ids(tail),
        [
            {"subtitle_id": item.subtitle_id, "zh": f"zh-{item.subtitle_id}"}
            for item in items[4:]
        ],
    )

    applied = editor._apply_semantic_group_translations(
        items,
        [first, tail],
        {1: first_translations, 2: tail_translations},
    )

    assert applied[2].subtitle_id == "S0003"
    assert applied[2].translated == ""
    assert all(item.translated == f"zh-{item.subtitle_id}" for item in applied[4:])


def test_whisperx_time_only_preserves_text_and_translation_while_retiming():
    source = ASRData([
        ASRDataSeg("Welcome to today's Deep Dive. We are unpacking the story.", 1000, 4300),
    ])
    ledger = ASRData([
        ASRDataSeg("Welcome", 1000, 1100),
        ASRDataSeg("to", 1100, 1200),
        ASRDataSeg("today's", 1200, 1400),
        ASRDataSeg("Deep", 1400, 1600),
        ASRDataSeg("Dive.", 1600, 1800),
        ASRDataSeg("We", 2600, 2700),
        ASRDataSeg("are", 2700, 2800),
        ASRDataSeg("unpacking", 2800, 3200),
        ASRDataSeg("the", 3200, 3300),
        ASRDataSeg("story.", 3300, 3600),
    ])
    aligned_words = [
        {"text": "Welcome", "start": 1.22, "end": 1.45},
        {"text": "to", "start": 1.46, "end": 1.56},
        {"text": "today's", "start": 1.57, "end": 1.82},
        {"text": "Deep", "start": 1.83, "end": 2.03},
        {"text": "Dive", "start": 2.04, "end": 2.25},
        {"text": "We", "start": 2.92, "end": 3.05},
        {"text": "are", "start": 3.06, "end": 3.18},
        {"text": "unpacking", "start": 3.19, "end": 3.55},
        {"text": "the", "start": 3.56, "end": 3.66},
        {"text": "story", "start": 3.67, "end": 3.96},
    ]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert [by_word_id[index].text for index in range(10)] == [
        segment.text for segment in ledger.segments
    ]
    assert by_word_id[0].start_time == 1220
    assert by_word_id[9].end_time == 3960
    assert all(by_word_id[index].alignment_source == "whisperx" for index in range(10))


def test_whisperx_frozen_ledger_keeps_only_unmatched_word_on_stable_ts_time():
    source = ASRData([ASRDataSeg("One two three.", 1000, 1600)])
    ledger = ASRData(
        [
            ASRDataSeg("One", 1000, 1100),
            ASRDataSeg("two", 1110, 1220),
            ASRDataSeg("three", 1230, 1400),
        ]
    )
    aligned_words = [
        {"text": "One", "start": 1.01, "end": 1.09},
        {"text": "three", "start": 1.30, "end": 1.52},
    ]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert (by_word_id[0].start_time, by_word_id[0].end_time) == (1010, 1090)
    assert (by_word_id[1].start_time, by_word_id[1].end_time) == (1110, 1220)
    assert (by_word_id[2].start_time, by_word_id[2].end_time) == (1300, 1520)
    assert by_word_id[1].alignment_source == "stable-ts-fallback"
    assert remapped.whisperx_matched_word_count == 2
    assert remapped.whisperx_fallback_word_count == 1


def test_whisperx_frozen_ledger_reverts_a_candidate_that_inverts_fallback_word_order():
    source = ASRData([ASRDataSeg("and 15 000", 592140, 593020)])
    ledger = ASRData(
        [
            ASRDataSeg("and", 592140, 592260),
            ASRDataSeg("15", 592260, 592640),
            ASRDataSeg("000", 592640, 593020),
        ]
    )
    aligned_words = [{"text": "and", "start": 592.917, "end": 593.017}]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert (by_word_id[0].start_time, by_word_id[0].end_time) == (592140, 592260)
    assert by_word_id[0].alignment_source == "stable-ts-fallback"
    assert [(segment.word_id, segment.text) for segment in remapped.segments] == [
        (0, "and"),
        (1, "15"),
        (2, "000"),
    ]
    assert remapped.whisperx_monotonicity_fallbacks == [
        {
            "code": "whisperx_monotonicity_fallback",
            "word_id": 0,
            "word": "and",
            "baseline_range_ms": [592140, 592260],
            "rejected_whisperx_range_ms": [592917, 593017],
            "conflicting_word_ids": [0, 1],
        }
    ]


def test_whisperx_frozen_ledger_keeps_monotonic_candidate_updates():
    source = ASRData([ASRDataSeg("One two", 1000, 1300)])
    ledger = ASRData([ASRDataSeg("One", 1000, 1100), ASRDataSeg("two", 1120, 1300)])
    aligned_words = [
        {"text": "One", "start": 1.20, "end": 1.30},
        {"text": "two", "start": 1.31, "end": 1.46},
    ]

    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        remapped = align_frozen_word_ledger_with_whisperx("unused.m4a", source, ledger)

    assert remapped is not None
    by_word_id = {segment.word_id: segment for segment in remapped.segments}
    assert (by_word_id[0].start_time, by_word_id[1].end_time) == (1200, 1460)
    assert all(by_word_id[index].alignment_source == "whisperx" for index in range(2))
    assert remapped.whisperx_monotonicity_fallbacks == []


def test_whisperx_time_only_falls_back_to_stable_ledger_without_changing_cues():
    class _Progress:
        def __init__(self):
            self.events = []

        def emit(self, *args):
            self.events.append(args)

    class _FallbackEditor:
        def __init__(self):
            self.alignment = None
            self.rebuild_backend = None

        def record_final_timeline_alignment(self, **kwargs):
            self.alignment = kwargs

        def rebuild_final_cue_timeline(self, asr_data, word_ledger, *, alignment_backend):
            self.rebuild_backend = alignment_backend
            return asr_data

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.task = type("Task", (), {"video_path": __file__})()
    thread.progress = _Progress()
    thread.tr = lambda value: value
    thread._record_stage_duration = lambda *args: None
    source = ASRData([ASRDataSeg("A stable cue.", 1000, 1600, "稳定字幕。")])
    source.segments[0].subtitle_id = "S0001"
    ledger = ASRData([ASRDataSeg("A", 1000, 1100), ASRDataSeg("stable", 1110, 1350)])
    editor = _FallbackEditor()

    with patch.object(SubtitleThread, "_timeline_alignment_backend", return_value="whisperx-time-only"), patch(
        "app.thread.subtitle_thread.align_frozen_word_ledger_with_whisperx",
        return_value=None,
    ):
        rebuilt = thread._apply_whisperx_time_only_if_enabled(
            source,
            alignment_source=source,
            word_ledger=ledger,
            screen_editor=editor,
        )

    assert rebuilt is source
    assert editor.rebuild_backend == "stable-ts-fallback"
    assert editor.alignment == {
        "requested_backend": "whisperx-time-only",
        "applied_backend": "stable-ts-fallback",
        "fallback_reason": "incomplete_frozen_word_ledger",
    }
    assert any("稳定词级时间轴" in event[1] for event in thread.progress.events)


def test_whisperx_time_only_uses_expanded_frozen_ledger_not_source_segment_count():
    """Final alignment must consume display words, not the coarser ASR spans.

    Stable cutting can expand a single ASR word span such as ``twenty-one``
    into several frozen display words.  The final alignment contract is the
    frozen ledger, even when it has more entries than the original ASR input.
    """
    class _Progress:
        def emit(self, *args):
            pass

    class _LedgerEditor:
        def __init__(self):
            self.alignment = None
            self.rebuilt_word_ids = []

        def record_final_timeline_alignment(self, **kwargs):
            self.alignment = kwargs

        def rebuild_final_cue_timeline(self, asr_data, word_ledger, *, alignment_backend):
            self.rebuilt_word_ids = [segment.word_id for segment in word_ledger.segments]
            assert alignment_backend == "whisperx-time-only"
            return asr_data

    thread = SubtitleThread.__new__(SubtitleThread)
    thread.task = type("Task", (), {"video_path": __file__})()
    thread.progress = _Progress()
    thread.tr = lambda value: value
    thread._record_stage_duration = lambda *args: None

    # Three original ASR spans expand into five frozen display words.
    alignment_source = ASRData(
        [
            ASRDataSeg("twenty-one", 0, 320),
            ASRDataSeg("founders", 330, 640),
            ASRDataSeg("arrived.", 650, 900),
        ]
    )
    final_cues = ASRData([ASRDataSeg("Twenty one founders arrived.", 0, 900, "二十一位创始人到了。")])
    final_cues.segments[0].subtitle_id = "S0001"
    ledger = ASRData(
        [
            ASRDataSeg("Twenty", 0, 120),
            ASRDataSeg("one", 120, 320),
            ASRDataSeg("founders", 330, 640),
            ASRDataSeg("arrived", 650, 820),
            ASRDataSeg(".", 820, 900),
        ]
    )
    for word_id, segment in enumerate(ledger.segments):
        segment.word_id = word_id
        segment.alignment_source = "whisperx"
    editor = _LedgerEditor()

    with patch.object(SubtitleThread, "_timeline_alignment_backend", return_value="whisperx-time-only"), patch(
        "app.thread.subtitle_thread.align_frozen_word_ledger_with_whisperx",
        return_value=ledger,
    ) as align:
        rebuilt = thread._apply_whisperx_time_only_if_enabled(
            final_cues,
            alignment_source=alignment_source,
            word_ledger=ledger,
            screen_editor=editor,
        )

    assert rebuilt is final_cues
    assert len(alignment_source.segments) == 3
    assert len(ledger.segments) == 5
    assert align.call_args.args[2] is ledger
    assert editor.rebuilt_word_ids == [0, 1, 2, 3, 4]
    assert editor.alignment["applied_backend"] == "whisperx-time-only"


def test_whisperx_time_only_uses_explicit_source_audio_from_complete_task():
    """E2E may separate the alignment input from the sidecar-report anchor."""
    class _Progress:
        def emit(self, *args):
            pass

    class _TimelineEditor:
        def __init__(self):
            self.alignment = None

        def record_final_timeline_alignment(self, **kwargs):
            self.alignment = kwargs

        def rebuild_final_cue_timeline(self, asr_data, word_ledger, *, alignment_backend):
            assert alignment_backend == "whisperx-time-only"
            return asr_data

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_audio = root / "source.m4a"
        source_audio.touch()
        source_subtitle = root / "source.srt"
        source_subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nA stable cue.\n", encoding="utf-8")
        report_dir = root / "e2e-reports"
        report_dir.mkdir()
        report_anchor = report_dir / "source-audio-report-anchor.m4a"
        task = TaskFactory.create_subtitle_task(
            str(source_subtitle),
            video_path=str(report_anchor),
            need_next_task=True,
            source_audio_path=str(source_audio),
        )

        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        thread.progress = _Progress()
        thread.tr = lambda value: value
        thread._record_stage_duration = lambda *args: None
        final_cues = ASRData([ASRDataSeg("A stable cue.", 1000, 1600, "稳定字幕。")])
        final_cues.segments[0].subtitle_id = "S0001"
        ledger = ASRData([ASRDataSeg("A", 1000, 1100), ASRDataSeg("stable", 1110, 1350)])
        editor = _TimelineEditor()

        with patch.object(SubtitleThread, "_timeline_alignment_backend", return_value="whisperx-time-only"), patch(
            "app.thread.subtitle_thread.align_frozen_word_ledger_with_whisperx",
            return_value=ledger,
        ) as align:
            rebuilt = thread._apply_whisperx_time_only_if_enabled(
                final_cues,
                alignment_source=final_cues,
                word_ledger=ledger,
                screen_editor=editor,
            )

        assert rebuilt is final_cues
        assert task.source_audio_path == str(source_audio)
        assert task.video_path == str(report_anchor)
        assert thread._source_audio_report_dir() == (
            report_dir / "source-处理结果"
        )
        assert align.call_args.args == (str(source_audio), final_cues, ledger)
        assert editor.alignment["applied_backend"] == "whisperx-time-only"


def test_screen_editor_normalizes_enum_target_language_for_prompts_and_artifacts():
    assert (
        ScreenSubtitleEditor._normalize_target_language(TargetLanguageEnum.CHINESE_SIMPLIFIED)
        == "简体中文"
    )
    assert ScreenSubtitleEditor._normalize_target_language("English") == "English"


def test_word_ledger_preserves_unicode_and_meaningful_connectors():
    entries = ScreenSubtitleEditor._word_time_entries(
        [ASRDataSeg("Nestl\u00e9, R&D and 100th.", 0, 400)]
    )

    assert [entry["surface"] for entry in entries] == [
        "Nestl\u00e9,",
        "R&D",
        "and",
        "100th.",
    ]


def test_short_nonindependent_backchannel_attaches_to_previous_display_item():
    previous_words = "This explanation has fourteen ordinary words and ends as a complete thought clearly today".split()
    words = previous_words + ["Yeah.", "The", "next", "sentence", "continues."]
    editor = _marker_editor(words, max_words=16)
    items = [
        _word_item(editor, 0, len(previous_words) - 1, 1),
        _word_item(editor, len(previous_words), len(previous_words), 2),
        _word_item(editor, len(previous_words) + 1, len(words) - 1, 3),
    ]

    merged = editor._merge_short_display_items(items)

    assert len(merged) == 2
    assert merged[0].original.endswith("Yeah.")
    assert ScreenSubtitleEditor._word_count(merged[0].original) == 15
    assert merged[1].original == "The next sentence continues."
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_short_backchannel_stays_with_following_coordinated_clause():
    previous_words = ["Model", "distillation."]
    next_words = (
        "And this is really the secret to how these developers are so drastically "
        "optimizing their costs."
    ).split()
    words = previous_words + ["Yeah."] + next_words
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    items = [
        _word_item(editor, 0, 1, 1),
        _word_item(editor, 2, 2, 2),
        _word_item(editor, 3, len(words) - 1, 3),
    ]

    merged = editor._merge_short_display_items(items)

    assert len(merged) == 2
    assert merged[0].original == "Model distillation."
    assert merged[1].original.startswith("Yeah. And this")
    assert merged[1].original.endswith("their costs.")
    assert ScreenSubtitleEditor._word_count(merged[1].original) == 17
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in merged)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_pre_id_validation_keeps_terminal_backchannel_out_of_previous_sentence():
    words = ["Model", "distillation.", "Yeah.", "And", "this", "works."]
    editor = _marker_editor(words, max_words=16)
    items = [
        _word_item(editor, 0, 1, 1),
        _word_item(editor, 2, 2, 2),
        _word_item(editor, 3, 5, 3),
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == [
        "Model distillation.",
        "Yeah. And this works.",
    ]
    assert ScreenSubtitleEditor._word_tokens(" ".join(item.original for item in repaired)) == ScreenSubtitleEditor._word_tokens(
        " ".join(item.original for item in items)
    )


def test_complete_unsplittable_overflow_is_warning_not_overlong_error():
    text = "A precise compact sentence keeps every protected grammatical relation intact through this final complete clause cleanly today."
    editor = _marker_editor(text.split(), max_words=16)
    segment = ASRDataSeg(text, 0, 3200, "完整中文。")
    segment.subtitle_id = "S0001"
    segment.word_start = 0
    segment.word_end = len(editor._active_word_entries) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])

    structural = editor._structural_english_overflow_issues([segment])
    overlong = editor._overlong_english_issues([segment])

    assert len(structural) == 1
    assert overlong == []
    health = {
        "overlong_english": overlong,
        "structural_english_overflow": structural,
        "bad_cuts": [],
        "translationese": [],
        "reading_speed_errors": [],
        "reading_speed_warnings": [],
        "duration_errors": [],
        "duration_warnings": [],
        "duplicate_chinese": [],
        "asr_suspicious": [],
        "discourse_marker_orphans": [],
        "syntax_boundary_audit": [],
        "chinese_semantic_group_warnings": [],
        "chinese_semantic_group_info": [],
    }
    summary = editor._validation_summary([], [], health, [segment])

    assert summary["errors"] == []
    assert [issue["code"] for issue in summary["warnings"]] == ["structural_english_overflow"]


def test_context_rejected_overlong_split_is_structural_warning_not_error():
    texts = [
        "without having to legally tether themselves to someone who can't match "
        "their life stage or financial success.",
        "If modern relationships are increasingly functioning as temporary tools "
        "for individual self-actualization and creative fuel rather than lifelong "
        "partnerships,",
        "what does that mean for the traditional romantic ideals you've been taught "
        "to value all your life?",
    ]
    words = " ".join(texts).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()

    ranges = []
    cursor = 0
    for text in texts:
        word_count = len(text.split())
        ranges.append((cursor, cursor + word_count - 1))
        cursor += word_count
    items = [_word_item(editor, start, end, 1) for start, end in ranges]

    repaired, _ = editor._safe_overlong_item_split(items[1])
    assert repaired == []

    segments = []
    for index, (text, (word_start, word_end)) in enumerate(zip(texts, ranges), start=1):
        segment = ASRDataSeg(text, word_start * 200, (word_end + 1) * 200, "完整中文。")
        segment.subtitle_id = f"S{index:04d}"
        segment.word_start = word_start
        segment.word_end = word_end
        segments.append(segment)

    assert editor._overlong_english_issues(segments) == []
    structural = editor._structural_english_overflow_issues(segments)
    assert "S0002" in [issue["subtitle_id"] for issue in structural]


def test_stable_cut_keeps_an_unsplittable_complete_sentence_renderer_owned():
    text = (
        "Well we started by noting that artificial intelligence is already drafting "
        "more than a third of all new websites on the internet."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)

    def only_incomplete_overflow_cut(left, *args, **kwargs):
        return {
            "legal": left == 18,
            "hard_issues": [] if left == 18 else ["protected_syntax_cut"],
            "boundary_score": 0.0,
        }

    editor._evaluate_stable_cut_boundary = only_incomplete_overflow_cut

    assert editor._stable_word_ranges_for_span((0, len(words) - 1)) == [
        (0, len(words) - 1)
    ]

    segment = ASRDataSeg(text, 0, 4400, "完整中文。")
    segment.subtitle_id = "S0001"
    segment.word_start = 0
    segment.word_end = len(words) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])

    assert editor._word_count(text) == 22
    assert editor._is_allowed_structural_english_overflow(segment, text, 22, 16)
    assert editor._overlong_english_issues([segment]) == []
    assert len(editor._structural_english_overflow_issues([segment])) == 1

    editor._safe_overlong_item_split = lambda item: ([item], [])
    assert len(editor._overlong_english_issues([segment])) == 1

    incomplete = ASRDataSeg(text.rstrip("."), 0, 4400, "完整中文。")
    incomplete.word_start = 0
    incomplete.word_end = len(words) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])
    assert len(editor._overlong_english_issues([incomplete])) == 1


def test_stable_cut_prefers_normal_limit_complete_clauses_over_twenty_word_spans():
    text = (
        "And you know the really strange consequence of that massive volume is that "
        "you are constantly swimming in synthetic text, yet the very tricks you "
        "probably used to spot it are completely contradicted by the latest linguistic data."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)

    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))

    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(words) - 1
    assert all(end - start + 1 <= 16 for start, end in ranges)
    items = [editor._item_from_word_span(start, end) for start, end in ranges]
    assert all(item is not None for item in items)
    assert all(
        editor._evaluate_item_pair_for_final_boundary(left, right)["legal"]
        for left, right in zip(items, items[1:])
    )


def test_overlong_repair_keeps_relative_clause_with_its_main_predicate():
    text = (
        "And you know the really strange consequence of that massive volume is that "
        "you are constantly swimming in synthetic text, yet the very tricks you "
        "probably used to spot it are completely contradicted by the latest linguistic data."
    )
    editor = _marker_editor(text.split(), max_words=16)
    editor._prepare_syntax_cut_hints()
    first = _word_item(editor, 0, 19, 1)
    second = _word_item(editor, 20, len(editor._active_word_entries) - 1, 1)

    split, candidates = editor._safe_overlong_item_split(second)

    assert split == []
    predicate_split = next(
        candidate
        for candidate in candidates
        if candidate["cuts"] == [[29, 30]]
    )
    assert "subject_finite_verb_split" in predicate_split["hard_issues"]
    assert predicate_split["continuation_display_issues"] == [
        "right_orphaned_finite_predicate"
    ]
    noun_phrase_split = next(
        candidate
        for candidate in candidates
        if candidate["cuts"] == [[23, 24]]
    )
    assert noun_phrase_split["continuation_display_issues"] == [
        "left_connector_led_noun_phrase_fragment"
    ]
    preposition_split = next(
        candidate
        for candidate in candidates
        if candidate["cuts"] == [[32, 33]]
    )
    assert preposition_split["continuation_display_issues"] == [
        "right_preposition_led_fragment"
    ]
    assert editor._repair_final_overlong_display_items([first, second]) == [first, second]


def test_final_pre_id_repair_keeps_the_relative_clause_with_its_predicate():
    text = (
        "And you know the really strange consequence of that massive volume is that "
        "you are constantly swimming in synthetic text, yet the very tricks you "
        "probably used to spot it are completely contradicted by the latest linguistic data."
    )
    editor = _marker_editor(text.split(), max_words=16)
    editor._prepare_syntax_cut_hints()
    items = [
        _word_item(editor, 0, 19, 1),
        _word_item(editor, 20, 32, 1),
        _word_item(editor, 33, len(editor._active_word_entries) - 1, 1),
    ]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [(item.word_start, item.word_end) for item in repaired] == [
        (0, 19),
        (20, len(editor._active_word_entries) - 1),
    ]
    assert repaired[1].original.endswith("latest linguistic data.")


def test_final_pre_id_repair_merges_subjectless_predicate_across_a_long_pause():
    text = (
        "And you know the really strange consequence of that massive volume is that "
        "you are constantly swimming in synthetic text, yet the very tricks you "
        "probably used to spot it are completely contradicted by the latest linguistic data."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    relative_start = words.index("yet")
    predicate_start = words.index("are", relative_start)
    for entry in editor._active_word_entries[predicate_start:]:
        entry["start_time"] += 400
        entry["end_time"] += 400
    items = [
        _word_item(editor, 0, relative_start - 1, 1),
        _word_item(editor, relative_start, predicate_start - 1, 1),
        _word_item(editor, predicate_start, len(words) - 1, 1),
    ]

    evaluation = editor._evaluate_item_pair_for_final_boundary(items[1], items[2], items[0])
    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert editor._boundary_pause_ms(items[1], items[2]) == 480
    assert evaluation["legal"] is False
    assert evaluation["continuation_display_issues"] == [
        "right_orphaned_finite_predicate"
    ]
    assert [(item.word_start, item.word_end) for item in repaired] == [
        (0, relative_start - 1),
        (relative_start, len(words) - 1),
    ]
    assert repaired[1].original == (
        "yet the very tricks you probably used to spot it are completely "
        "contradicted by the latest linguistic data."
    )


def test_stable_cut_does_not_leave_terminal_prepositional_phrase():
    text = (
        "By one estimate artificial intelligence is currently drafting more than "
        "a third of all new websites on the internet."
    )
    editor = _marker_editor(text.split(), max_words=16)

    def only_prepositional_fragment_cut(left, *args, **kwargs):
        return {
            "legal": left == 15,
            "hard_issues": [] if left == 15 else ["protected_syntax_cut"],
            "boundary_score": 0.0,
        }

    editor._evaluate_stable_cut_boundary = only_prepositional_fragment_cut

    ranges = editor._stable_word_ranges_for_span((0, len(text.split()) - 1))

    assert ranges == [(0, len(text.split()) - 1)]


def test_comma_terminated_parser_confirmed_subordinate_overflow_is_warning_not_error():
    text = "Yeah. And now that mobile coffee cart is bringing in between 10 000 and 15 000 every single month,"
    editor = _marker_editor(text.split(), max_words=16)
    segment = ASRDataSeg(text, 0, 6000, "完整中文。")
    segment.subtitle_id = "S0001"
    segment.word_start = 0
    segment.word_end = len(editor._active_word_entries) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])

    assert editor._word_count(text) == 19
    assert editor._is_allowed_structural_english_overflow(segment, text, 19, 16)
    assert editor._overlong_english_issues([segment]) == []
    assert len(editor._structural_english_overflow_issues([segment])) == 1


def test_comma_overflow_requires_parser_proof_and_no_safe_split():
    text = "Yeah. And now that mobile coffee cart is bringing in between 10 000 and 15 000 every single month,"
    editor = _marker_editor(text.split(), max_words=16)
    segment = ASRDataSeg(text, 0, 6000, "完整中文。")
    segment.word_start = 0
    segment.word_end = len(editor._active_word_entries) - 1
    editor._safe_overlong_item_split = lambda item: ([], [])

    with patch.object(editor, "_load_syntax_nlp", return_value=None):
        assert not editor._is_allowed_structural_english_overflow(segment, text, 19, 16)

    editor._safe_overlong_item_split = lambda item: ([item], [])
    assert not editor._is_allowed_structural_english_overflow(segment, text, 19, 16)


def test_visual_reading_budget_keeps_complete_13_word_cue_for_renderer_wrapping():
    words = "The market changed quickly after years of steady growth, and investors are responding.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_keeps_character_heavy_cue_for_renderer_wrapping():
    words = "Internationalization creates a comprehensive institutional transformation across decentralized communities today.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    assert ScreenSubtitleEditor._word_count(original.original) <= 12
    assert editor._visible_english_character_count(original.original) > 68

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_never_selects_preposition_object_cut():
    words = "She is the founder of a non-profit organization that helps young people find careers.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_does_not_create_a_review_for_renderer_wrapping():
    words = "The market changed quickly after years of steady growth, and investors took notice.".split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)
    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_keeps_short_open_phrase_with_its_sentence():
    words = (
        "It turns out that the most famous giveaway of AI-generated text, "
        "the word delve, signals a formulaic style."
    ).split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    repaired = editor._apply_visual_reading_budget([original])

    assert all(item.original != "the word delve," for item in repaired)
    phrase = _word_item(editor, 11, 13, 1)
    issues = editor._visual_split_display_unit_issues(phrase, None, None)
    assert "visual_open_phrase_fragment" in issues


def test_visual_reading_budget_keeps_a_single_clause_for_renderer_wrapping():
    words = (
        "But the thing I keep coming back to is how fast this is evolving."
    ).split()
    editor = _marker_editor(words, max_words=16)
    original = _word_item(editor, 0, len(words) - 1, 1)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_reading_budget_rejects_short_preposition_led_display_tail():
    words = "Our editors write clear explanations with punchy statements.".split()
    editor = _marker_editor(words, max_words=16)
    tail = _word_item(editor, 5, len(words) - 1, 1)

    issues = editor._visual_split_display_unit_issues(tail, _word_item(editor, 0, 4, 1), None)

    assert "visual_preposition_led_fragment" in issues


def test_visual_reading_budget_never_creates_parser_confirmed_example_preposition_cut():
    words = (
        "Researchers still look for outdated clues like excessive em dashes "
        "in generated prose today."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)

    evaluation = editor._evaluate_stable_cut_boundary(6, 7)
    repaired = editor._apply_visual_reading_budget([original])

    assert "preposition_object_split" in evaluation["hard_issues"]
    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_stable_cut_keeps_comma_bracketed_adverb_with_preceding_list_item():
    words = (
        "I mean, the stakes here are massive for you, for me, really, "
        "for anyone reading anything on the screen right now."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()

    evaluation = editor._evaluate_stable_cut_boundary(10, 11)
    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))
    selected_boundaries = {end for _, end in ranges[:-1]}

    assert "comma_bracketed_adverb_split" in evaluation["hard_issues"]
    # The optimizer may choose the earlier balanced list boundary, but the
    # protected ``for me, really,`` unit must remain together in one cue.
    assert 10 not in selected_boundaries
    assert 11 not in selected_boundaries
    assert any(
        "for me, really," in " ".join(words[start:end + 1])
        for start, end in ranges
    )


def test_visual_budget_keeps_subject_with_delayed_finite_predicate():
    words = "Yeah. Well, the judges specifically praised its, quote, quiet authority.".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)

    evaluation = editor._evaluate_stable_cut_boundary(3, 4)
    repaired = editor._apply_visual_reading_budget([original])

    assert "subject_finite_verb_split" in evaluation["hard_issues"]
    assert repaired == [original]


def test_visual_budget_keeps_short_gerundial_manner_phrase_with_main_question():
    words = "How can you actually spot the ghost in the machine using your own eyes?".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    evaluation = editor._evaluate_stable_cut_boundary(9, 10)
    repaired = editor._apply_visual_reading_budget([original])
    preposition_tail = _word_item(editor, 7, len(words) - 1, 1)

    assert "short_gerundial_modifier_split" in evaluation["hard_issues"]
    assert repaired == [original]
    assert "visual_preposition_led_fragment" in editor._visual_split_display_unit_issues(
        preposition_tail,
        _word_item(editor, 0, 6, 1),
        None,
    )
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def _add_visual_pause(editor, cut_after, pause_ms):
    original_pause = (
        editor._active_word_entries[cut_after + 1]["start_time"]
        - editor._active_word_entries[cut_after]["end_time"]
    )
    delta = pause_ms - original_pause
    for entry in editor._active_word_entries[cut_after + 1:]:
        entry["start_time"] += delta
        entry["end_time"] += delta


def test_v10_adjacent_rebalance_moves_short_time_adjunct_to_previous_cue():
    text = (
        "American tech giants are projected to spend, like, a staggering 740 "
        "billion on data centers this year alone, with Alphabet boosting its AI "
        "spend to 205 billion."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    _add_visual_pause(editor, words.index("alone,"), 320)
    items = [
        _word_item(editor, 0, words.index("centers"), 1),
        _word_item(editor, words.index("this"), len(words) - 1, 1),
    ]

    rebalanced = editor._rebalance_adjacent_pre_id_windows(items)

    assert [item.original for item in rebalanced] == [
        "American tech giants are projected to spend, like, a staggering 740 "
        "billion on data centers this year alone,",
        "with Alphabet boosting its AI spend to 205 billion.",
    ]

    guard_text = (
        "Demand kept rising. In China, companies expanded production quickly."
    )
    guard_words = guard_text.split()
    guard_editor = _marker_editor(guard_words, max_words=16)
    guard_editor._prepare_syntax_cut_hints()
    _add_visual_pause(guard_editor, guard_words.index("China,"), 320)
    guard_items = [
        _word_item(guard_editor, 0, guard_words.index("rising."), 1),
        _word_item(
            guard_editor,
            guard_words.index("In"),
            len(guard_words) - 1,
            1,
        ),
    ]

    guarded = guard_editor._rebalance_adjacent_pre_id_windows(guard_items)

    assert [(item.word_start, item.word_end) for item in guarded] == [
        (0, guard_words.index("rising.")),
        (guard_words.index("In"), len(guard_words) - 1),
    ]


def test_v10_adjacent_rebalance_merges_dependent_two_word_tails():
    cases = [
        (
            "Because the reports show regulators in Beijing are actively pushing "
            "the domestic industry to, like, sanction-proof. Their infrastructure.",
            15,
        ),
        (
            "The headline, capital expenditure figures in the U S. capture massive "
            "purchases of off-the shelf ultra-premium hardware.",
            14,
        ),
        (
            "A screwdriver that the domestic industrial sector is actively seeking "
            "to integrate into their margins right now.",
            14,
        ),
    ]
    for text, cut_after in cases:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        items = [
            _word_item(editor, 0, cut_after, 1),
            _word_item(editor, cut_after + 1, len(words) - 1, 1),
        ]

        rebalanced = editor._rebalance_adjacent_pre_id_windows(items)

        assert [item.original for item in rebalanced] == [text]

    independent_text = "The demand was enormous. A real breakthrough."
    independent_words = independent_text.split()
    independent_editor = _marker_editor(independent_words, max_words=16)
    independent_editor._prepare_syntax_cut_hints()
    independent_items = [
        _word_item(
            independent_editor,
            0,
            independent_words.index("enormous."),
            1,
        ),
        _word_item(
            independent_editor,
            independent_words.index("A"),
            len(independent_words) - 1,
            1,
        ),
    ]

    guarded = independent_editor._rebalance_adjacent_pre_id_windows(
        independent_items
    )

    assert [(item.word_start, item.word_end) for item in guarded] == [
        (0, independent_words.index("enormous.")),
        (independent_words.index("A"), len(independent_words) - 1),
    ]


def test_adjacent_rebalance_preserves_sentence_boundary_before_complete_short_tail():
    text = (
        "We are going to figure out why Hollywood is suddenly obsessed with this "
        "exact dynamic. Lots of money."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    sentence_end = words.index("dynamic.")
    items = [
        _word_item(editor, 0, sentence_end, 1),
        _word_item(editor, sentence_end + 1, len(words) - 1, 1),
    ]

    merged = editor._merge_subtitle_items(*items)
    safe_split, _ = editor._safe_overlong_item_split(merged)
    rebalanced = editor._rebalance_adjacent_pre_id_windows(items)

    assert [(item.word_start, item.word_end) for item in safe_split] == [
        (0, sentence_end),
        (sentence_end + 1, len(words) - 1),
    ]
    assert [(item.word_start, item.word_end) for item in rebalanced] == [
        (0, sentence_end),
        (sentence_end + 1, len(words) - 1),
    ]
    assert editor._pre_id_boundary_repairs == []


def test_v10_preposition_only_tail_keeps_complete_sentence_renderer_owned():
    text = (
        "The much smaller Chinese budgets reflect intense engineering labor to "
        "squeeze every last drop of performance out of restricted, imperfect hardware."
    )
    words = text.split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()

    ranges = editor._stable_word_ranges_for_span((0, len(words) - 1))

    assert ranges == [(0, len(words) - 1)]


def test_v10_adjacent_rebalance_preserves_approved_boundaries():
    approved = [
        (
            "Like the land for the data centers, the servers, the concrete, the "
            "salaries of the engineers writing the code.",
            6,
        ),
        (
            "Like a small Chinese model looking over the shoulder of an American "
            "model and just copying its homework?",
            12,
        ),
    ]
    for text, cut_after in approved:
        words = text.split()
        editor = _marker_editor(words, max_words=16)
        editor._prepare_syntax_cut_hints()
        items = [
            _word_item(editor, 0, cut_after, 1),
            _word_item(editor, cut_after + 1, len(words) - 1, 1),
        ]
        if cut_after == 12:
            left_source = ASRDataSeg(items[0].original, 0, 1000, "")
            right_source = ASRDataSeg(items[1].original, 1010, 2000, "")
            left_source.speaker = "A"
            right_source.speaker = "B"
            editor._active_source_segments_by_id = {1: left_source, 2: right_source}
            items[0].source_ids = [1]
            items[1].source_ids = [2]

        rebalanced = editor._rebalance_adjacent_pre_id_windows(items)

        assert [(item.word_start, item.word_end) for item in rebalanced] == [
            (0, cut_after),
            (cut_after + 1, len(words) - 1),
        ]


def test_visual_temporal_budget_does_not_override_protected_fronted_introduction():
    words = (
        "Reading about these polysyllables and nominalizations, "
        "it immediately brings George Orwell to mind."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 5, 420)
    word_times_before = [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ]

    repaired = editor._apply_visual_reading_budget([original])

    assert [item.original for item in repaired] == [original.original]
    assert [item.word_start for item in repaired] == [0]
    assert [item.word_end for item in repaired] == [12]
    assert [
        (entry["start_time"], entry["end_time"])
        for entry in editor._active_word_entries
    ] == word_times_before


def test_visual_temporal_budget_splits_complete_punctuated_clauses():
    words = (
        "Humans might say things are connected, but the AI talks about "
        "their interdependence."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 5, 420)

    repaired = editor._apply_visual_reading_budget([original])

    assert [item.original for item in repaired] == [
        "Humans might say things are connected,",
        "but the AI talks about their interdependence.",
    ]
    assert editor._pre_id_boundary_repairs[0]["visual_temporal_category"] == (
        "complete_clause_boundary"
    )


def test_visual_temporal_budget_splits_complete_sentence_terminal():
    words = (
        "The first report confirms a meaningful trend. The next report explains "
        "the remaining uncertainty."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 6, 180)

    repaired = editor._apply_visual_reading_budget([original])

    assert [item.original for item in repaired] == [
        "The first report confirms a meaningful trend.",
        "The next report explains the remaining uncertainty.",
    ]
    assert editor._pre_id_boundary_repairs[0]["visual_temporal_category"] == (
        "sentence_terminal"
    )


def test_visual_temporal_budget_splits_complete_imperative_sentence_terminal():
    words = (
        "Consider the evidence from every relevant perspective. The next report explains "
        "the remaining uncertainty."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 6, 180)

    repaired = editor._apply_visual_reading_budget([original])

    assert [item.original for item in repaired] == [
        "Consider the evidence from every relevant perspective.",
        "The next report explains the remaining uncertainty.",
    ]
    assert [item.word_start for item in repaired] == [0, 7]
    assert [item.word_end for item in repaired] == [6, 13]
    assert editor._pre_id_boundary_repairs[0]["visual_temporal_category"] == (
        "sentence_terminal"
    )


def test_visual_temporal_budget_keeps_to_infinitive_with_its_main_clause():
    words = (
        "To consider the evidence from every relevant perspective is useful. "
        "The next report explains the remaining uncertainty."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 9, 180)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_visual_temporal_budget_keeps_subject_with_delayed_predicate_despite_pause():
    words = (
        "You know, this robotic vocabulary actually connects to a very human "
        "critique from way back."
    ).split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 4, 280)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []
    evaluation = editor._evaluate_stable_cut_boundary(4, 5)
    assert "subject_finite_verb_split" in evaluation["hard_issues"]


def test_visual_temporal_budget_rejects_punctuated_conditional_intro():
    words = "If I normally say, uh, I'm going to eat a sandwich for lunch.".split()
    editor = _marker_editor(words, max_words=16)
    editor._prepare_syntax_cut_hints()
    original = _word_item(editor, 0, len(words) - 1, 1)
    _add_visual_pause(editor, 4, 320)

    repaired = editor._apply_visual_reading_budget([original])

    assert repaired == [original]
    assert editor._pre_id_boundary_repairs == []


def test_final_timeline_rebuild_preserves_id_text_chinese_and_word_ownership():
    editor = _editor()
    editor._active_word_entries = [
        {"token": "i", "surface": "I", "start_time": 553220, "end_time": 553340},
        {"token": "mean", "surface": "mean", "start_time": 553350, "end_time": 553500},
        {"token": "the", "surface": "the", "start_time": 553510, "end_time": 553620},
        {"token": "delve", "surface": "Delve", "start_time": 553630, "end_time": 553900},
        {"token": "era", "surface": "era", "start_time": 553910, "end_time": 554100},
        {"token": "is", "surface": "is", "start_time": 554110, "end_time": 554220},
        {"token": "over", "surface": "over.", "start_time": 554230, "end_time": 555720},
        {"token": "why", "surface": "Why", "start_time": 555730, "end_time": 555960},
    ]
    editor._frozen_subtitle_ids = ["S0187", "S0188"]
    final_data = ASRData(
        [
            ASRDataSeg("I mean, the Delve era is over.", 553180, 555284, "我的意思是，Delve时代结束了。"),
            ASRDataSeg("Why does its style change so rapidly?", 555324, 557100, "为什么它的风格变化这么快？"),
        ]
    )
    for index, segment in enumerate(final_data.segments):
        segment.subtitle_id = editor._frozen_subtitle_ids[index]
        segment.word_start = 0 if index == 0 else 7
        segment.word_end = 6 if index == 0 else 7
    final_data.segments.reverse()

    ledger = ASRData([])
    for word_id, entry in enumerate(editor._active_word_entries):
        word = ASRDataSeg(entry["surface"], entry["start_time"], entry["end_time"])
        word.word_id = word_id
        word.alignment_source = "whisperx"
        ledger.segments.append(word)

    before = {
        segment.subtitle_id: (
            segment.text,
            segment.translated_text,
            segment.word_start,
            segment.word_end,
        )
        for segment in final_data.segments
    }
    rebuilt = editor.rebuild_final_cue_timeline(
        final_data,
        ledger,
        alignment_backend="whisperx-time-only",
    )
    after = {
        segment.subtitle_id: (
            segment.text,
            segment.translated_text,
            segment.word_start,
            segment.word_end,
        )
        for segment in rebuilt.segments
    }

    assert after == before
    assert [segment.subtitle_id for segment in rebuilt.segments] == ["S0187", "S0188"]
    assert rebuilt.segments[0].end_time >= 555720
    assert editor._final_cue_timeline["validation"]["status"] == "PASS"
    assert editor._final_cue_timeline["expected_subtitle_ids"] == ["S0187", "S0188"]
    assert [record["subtitle_id"] for record in editor._final_cue_timeline["records"]] == [
        "S0187",
        "S0188",
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "final.srt"
        rebuilt.to_srt(save_path=str(output), layout="原文在上")
        rendered = output.read_text(encoding="utf-8-sig")
    assert "I mean, the Delve era is over." in rendered
    assert "我的意思是，Delve时代结束了。" in rendered


def test_forced_alignment_finalization_never_moves_timing():
    editor = _editor()
    asr_data = ASRData([
        ASRDataSeg("A short line.", 1000, 1220, "一条很短的字幕。"),
        ASRDataSeg("The next line.", 1260, 2200, "下一条字幕。"),
    ])
    for index, seg in enumerate(asr_data.segments, 1):
        seg.subtitle_id = f"S{index:04d}"
    before = [(seg.start_time, seg.end_time) for seg in asr_data.segments]
    editor._last_semantic_groups = []
    editor._last_subtitle_items = []
    editor._write_coverage_report = lambda *args, **kwargs: None

    repaired = editor.repair_after_final_time_alignment(
        asr_data,
        preserve_aligned_timing=True,
    )

    assert [(seg.start_time, seg.end_time) for seg in repaired.segments] == before


def test_failed_validation_does_not_write_final_output_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        task = SubtitleTask(
            subtitle_path=str(root / "source.srt"),
            output_path=str(root / "output.ass"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )
        summary = {
            "status": "ERROR",
            "errors": [{"code": "final_translation_id_mismatch"}],
            "warnings": [],
            "info": [],
        }

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "")]),
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="failed",
            validation_summary=summary,
        )

        failure = json.loads((root / "stable-last-failure.json").read_text(encoding="utf-8"))
        assert failure["render_blocked"] is True
        assert not (root / "output.ass").exists()
        assert not (root / "stable-final-manifest.json").exists()
        assert not (root / "stable-final-original-top.srt").exists()


def test_invalid_final_timeline_blocks_before_display_page_translation():
    thread = SubtitleThread.__new__(SubtitleThread)
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor._final_cue_timeline = {
        "validation": {
            "status": "ERROR",
            "errors": [
                {
                    "code": "final_timeline_word_coverage_incomplete",
                    "missing_word_ids": [0, 3],
                }
            ],
        }
    }

    try:
        thread._require_valid_final_timeline_before_display_pages(editor)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("invalid final timeline must block before page translation")

    assert "final_cue_timeline_invalid_before_display_pages" in message
    assert "final_timeline_word_coverage_incomplete" in message


def test_failed_display_page_translation_skips_network_quality_audit():
    segment = ASRDataSeg("A fixed English cue.", 0, 2000, "固定中文。")
    segment.subtitle_id = "S0001"
    editor = SimpleNamespace(
        _display_page_translation_artifact={
            "status": "ERROR",
            "errors": [{"code": "display_page_translation_request_failed"}],
        }
    )

    with tempfile.TemporaryDirectory() as temp_dir, patch(
        "app.thread.subtitle_thread.audit_fixed_id_translation_quality"
    ) as audit, patch(
        "app.thread.subtitle_thread.write_subtitle_review_ledger"
    ):
        payload = SubtitleThread._run_translation_quality_audit(
            editor,
            SimpleNamespace(segments=[segment]),
            str(Path(temp_dir) / "coverage-report.txt"),
        )

    audit.assert_not_called()
    assert payload["status"] == "SKIPPED"
    assert payload["batch_errors"] == [
        {"code": "translation_quality_audit_skipped_page_projection_failed"}
    ]


def test_non_structural_validation_errors_do_not_block_render_gate():
    editor = _id_editor()
    editor._translation_structure_errors = []
    editor.last_validation_summary = {
        "status": "ERROR",
        "errors": [{"code": "subtitle_duration_invalid"}],
        "warnings": [],
        "info": [],
    }

    assert editor.has_blocking_validation_errors() is False
    assert editor.blocking_validation_message() == ""


def test_blocking_timeline_message_is_chinese_and_keeps_subtitle_position():
    editor = _id_editor()
    editor._translation_structure_errors = []
    editor._final_cue_timeline = {
        "validation": {
            "status": "ERROR",
            "errors": [
                {
                    "code": "final_timeline_display_duration_invalid",
                    "subtitle_id": "S0019",
                    "message": "Final cue display duration is below the hard minimum.",
                }
            ],
        }
    }

    message = editor.blocking_validation_message()

    assert "字幕太短" in message
    assert "S0019" in message
    assert "Final cue" not in message


def test_final_segment_count_mismatch_is_structural_error():
    editor = _id_editor()
    editor._assign_global_subtitle_ids(_id_items(4))

    segments = [
        ASRDataSeg("English 1.", 0, 1000, "zh-S0001"),
        ASRDataSeg("English 2.", 1000, 2000, "zh-S0002"),
        ASRDataSeg("English 4.", 3000, 4000, "zh-S0004"),
    ]
    for segment, subtitle_id in zip(segments, ["S0001", "S0002", "S0004"]):
        segment.subtitle_id = subtitle_id
    editor._validate_final_segment_translation_ids(segments)

    assert "final_translation_id_mismatch" in _codes(editor)
    assert editor._translation_structure_errors[-1]["missing_subtitle_ids"] == ["S0003"]


def test_merge_preserves_ids_when_order_changes_before_final_write():
    editor = _id_editor()
    segments = _id_segments(4)
    editor._frozen_subtitle_ids = ["S0001", "S0002", "S0003", "S0004"]

    shuffled = [segments[2], segments[0], segments[3], segments[1]]
    ordered = editor._order_segments_by_frozen_subtitle_ids(shuffled)

    assert [seg.subtitle_id for seg in ordered] == editor._frozen_subtitle_ids
    assert [seg.text for seg in ordered] == [seg.text for seg in segments]


def test_repair_only_modifies_the_target_subtitle_id():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = "LONG_TARGET"

    def severe(seg):
        return seg.translated_text == "LONG_TARGET"

    def request(prompt, payload, task, temperature):
        return {"items": [{"subtitle_id": "S0002", "chinese": "这是修复文本"}]}

    with patch.object(editor, "_is_severe_chinese_speed", side_effect=severe), patch.object(
        editor, "_request_chinese_compression", side_effect=request
    ):
        repaired = editor._compress_fast_chinese_segments(segments)

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002", "S0003"]
    assert repaired[0].translated_text == "这是原文"
    assert repaired[1].translated_text == "这是修复文本"
    assert repaired[2].translated_text == "这是原文"


def test_compression_accepts_new_subtitle_id_protocol_without_position_shift():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = "LONG_TARGET"

    def severe(seg):
        return seg.translated_text == "LONG_TARGET"

    def request(prompt, payload, task, temperature):
        assert payload[0]["subtitle_id"] == "S0002"
        return {"items": [{"subtitle_id": "S0002", "chinese": "这是修复文本"}]}

    with patch.object(editor, "_is_severe_chinese_speed", side_effect=severe), patch.object(
        editor, "_request_chinese_compression", side_effect=request
    ):
        repaired = editor._compress_fast_chinese_segments(segments)

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002", "S0003"]
    assert repaired[0].translated_text == "这是原文"
    assert repaired[1].translated_text == "这是修复文本"


def test_compression_rejects_legacy_index_only_response_without_writeback():
    editor = _id_editor()
    segments = [
        ASRDataSeg("First line.", 0, 1000, "第一条原文"),
        ASRDataSeg("Second line.", 1000, 2000, "第二条原文很长"),
    ]
    for index, segment in enumerate(segments, 1):
        segment.subtitle_id = f"S{index:04d}"

    with patch.object(editor, "_is_severe_chinese_speed", side_effect=lambda seg: seg.subtitle_id == "S0002"), patch.object(
        editor,
        "_request_chinese_compression",
        return_value={"items": [{"index": 1, "chinese": "错误位置写回"}]},
    ):
        repaired = editor._compress_fast_chinese_segments(segments)

    assert [segment.translated_text for segment in repaired] == [
        "第一条原文",
        "第二条原文很长",
    ]
    assert any(
        issue["code"] == "translation_id_missing"
        for issue in editor._translation_structure_errors
    )


def test_group_reallocation_rejects_legacy_index_only_response():
    editor = _id_editor()
    segments = [ASRDataSeg("First line.", 0, 1000, "第一条原文")]
    segments[0].subtitle_id = "S0001"

    parsed = editor._parse_chinese_group_allocations(
        {
            "groups": [
                {
                    "target_index": 0,
                    "segments": [{"index": 0, "zh": "错误位置写回"}],
                }
            ]
        },
        segments,
    )

    assert parsed == {}
    assert any(
        issue["code"] == "translation_id_missing"
        for issue in editor._translation_structure_errors
    )


def test_redistribution_parses_out_of_order_returns_by_subtitle_id():
    editor = _id_editor()
    segments = _id_segments(4)
    data = {
        "groups": [
            {
                "target_subtitle_id": "S0003",
                "segments": [
                    {"subtitle_id": "S0004", "zh": "这是第四条"},
                    {"subtitle_id": "S0002", "zh": "这是第二条"},
                ],
            }
        ]
    }

    parsed = editor._parse_chinese_group_allocations(data, segments)

    assert parsed == {"S0003": {"S0004": "这是第四条", "S0002": "这是第二条"}}


def test_redistribution_parses_new_id_only_protocol_without_position_shift():
    editor = _id_editor()
    segments = _id_segments(4)
    data = {
        "groups": [
            {
                "target_subtitle_id": "S0003",
                "segments": [
                    {"subtitle_id": "S0004", "zh": "这是第四条"},
                    {"subtitle_id": "S0002", "zh": "这是第二条"},
                ],
            }
        ]
    }

    parsed = editor._parse_chinese_group_allocations(data, segments)

    assert parsed == {"S0003": {"S0004": "这是第四条", "S0002": "这是第二条"}}


def test_terminal_punctuation_inheritance_does_not_stack_period_after_comma():
    assert ScreenSubtitleEditor._inherit_terminal_chinese_punctuation(
        "旧句子。",
        "承接下一条，",
    ) == "承接下一条，"
    assert ScreenSubtitleEditor._inherit_terminal_chinese_punctuation(
        "旧句子。",
        "完整新句子",
    ) == "完整新句子。"


def test_compression_keeps_subtitle_ids_and_count():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = "LONG_TARGET"

    def severe(seg):
        return seg.translated_text == "LONG_TARGET"

    def request(prompt, payload, task, temperature):
        return {"items": [{"subtitle_id": "S0002", "chinese": "这是压缩文本"}]}

    with patch.object(editor, "_is_severe_chinese_speed", side_effect=severe), patch.object(
        editor, "_request_chinese_compression", side_effect=request
    ):
        compressed = editor._compress_fast_chinese_segments(segments)

    assert len(compressed) == len(segments)
    assert [seg.subtitle_id for seg in compressed] == [seg.subtitle_id for seg in segments]
    assert compressed[1].translated_text == "这是压缩文本"


def test_fallback_translation_fills_only_one_missing_subtitle_id():
    editor = _id_editor()
    segments = _id_segments(3)
    segments[1].translated_text = ""

    with patch.object(editor, "_translate_split_parts", return_value=["这是补译"]):
        repaired = editor._translate_missing_segments(segments)

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002", "S0003"]
    assert repaired[0].translated_text == "这是原文"
    assert repaired[1].translated_text == "这是补译"
    assert repaired[2].translated_text == "这是原文"


def test_multiple_semantic_groups_apply_by_id_without_drift():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(6))
    groups = [_id_group(1, 0, items[:3]), _id_group(2, 3, items[3:])]
    translations = {
        1: {"S0003": "zh-S0003", "S0001": "zh-S0001", "S0002": "zh-S0002"},
        2: {"S0006": "zh-S0006", "S0005": "zh-S0005", "S0004": "zh-S0004"},
    }

    applied = editor._apply_semantic_group_translations(items, groups, translations)

    assert [item.subtitle_id for item in applied] == [f"S{index:04d}" for index in range(1, 7)]
    assert [item.translated for item in applied] == [f"zh-S{index:04d}" for index in range(1, 7)]


def test_full_merge_repair_chain_keeps_400_plus_ids_without_drift():
    editor = _id_editor()
    editor.max_english_words = 14
    segments = _id_segments(405)
    editor._frozen_subtitle_ids = [seg.subtitle_id for seg in segments]

    repaired = editor._repair_blocking_subtitle_issues(segments)
    repaired = editor._merge_short_display_segments(repaired)
    repaired = editor._repair_abnormal_timing_gaps(repaired)
    repaired = editor._apply_display_timing_padding(repaired)
    repaired = editor._order_segments_by_frozen_subtitle_ids(repaired)
    editor._validate_final_segment_translation_ids(repaired)

    assert editor._translation_structure_errors == []
    assert [seg.subtitle_id for seg in repaired] == editor._frozen_subtitle_ids
    assert [seg.text for seg in repaired] == [seg.text for seg in segments]


def test_safe_auto_repair_is_noop_when_disabled():
    editor = _id_editor()
    editor.enable_safe_auto_repair = False
    segments = [
        ASRDataSeg("First different sentence.", 0, 1500, "这是明显重复的中文。"),
        ASRDataSeg("Second different sentence.", 1500, 3000, "这是明显重复的中文。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.text for seg in repaired] == [seg.text for seg in segments]
    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]


def test_safe_auto_repair_retranslates_exact_duplicate_chinese_by_id():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg("First different sentence.", 0, 1800, "这是明显重复的中文。"),
        ASRDataSeg("Second different sentence.", 1800, 3600, "这是明显重复的中文。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    with patch.object(editor, "_translate_split_parts", return_value=["第二句正确中文。"]):
        repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002"]
    assert [seg.text for seg in repaired] == [seg.text for seg in segments]
    assert [(seg.start_time, seg.end_time) for seg in repaired] == [
        (seg.start_time, seg.end_time) for seg in segments
    ]
    assert repaired[0].translated_text == "这是明显重复的中文。"
    assert repaired[1].translated_text == "第二句正确中文。"
    assert editor._safe_auto_repair_log
    assert editor._safe_auto_repair_log[-1]["subtitle_id"] == "S0002"


def test_safe_auto_repair_extends_high_load_short_subtitle_when_neighbor_has_room():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg(
            "He is trying to prevent the natural price discovery of the market.",
            1000,
            1700,
            "他试图阻止市场自然的价格发现机制。",
        ),
        ASRDataSeg("And the next sentence has enough room.", 1740, 5200, "下一句有足够空间。"),
    ]

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[0].end_time - repaired[0].start_time > 700
    assert repaired[0].end_time <= repaired[1].start_time - 40
    assert repaired[0].text == segments[0].text
    assert repaired[0].translated_text == segments[0].translated_text
    assert any(item["code"] == "high_load_short_timing_repaired" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_does_not_extend_high_load_short_subtitle_when_disabled():
    editor = _id_editor()
    editor.enable_safe_auto_repair = False
    segments = [
        ASRDataSeg(
            "He is trying to prevent the natural price discovery of the market.",
            1000,
            1700,
            "他试图阻止市场自然的价格发现机制。",
        ),
        ASRDataSeg("And the next sentence has enough room.", 1740, 5200, "下一句有足够空间。"),
    ]

    repaired = editor._repair_final_short_subtitle_timings(segments)

    assert repaired[0].end_time - repaired[0].start_time < editor._target_high_load_duration_ms(segments[0])
    assert repaired[0].text == segments[0].text


def test_duration_audit_reports_high_load_short_subtitle_as_warning():
    editor = _id_editor()
    segments = [
        ASRDataSeg(
            "He is trying to prevent the natural price discovery of the market.",
            1000,
            1700,
            "他试图阻止市场自然的价格发现机制。",
        )
    ]

    issues = editor._subtitle_duration_issues(segments, "WARNING")

    assert issues
    assert issues[0]["code"] == "subtitle_high_load_too_short"


def test_safe_auto_repair_records_review_candidates_without_rewriting_fragments():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_candidates = []
    segments = [
        ASRDataSeg("Yes, this is the key part.", 0, 1200, "是的，这是关键部分。因为"),
        ASRDataSeg("The next idea is separate.", 1240, 2600, "下一点是分开的。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"

    repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]
    assert any(
        item["code"] == "candidate_chinese_fragment_review_only"
        and item["decision"] == "not_auto_repaired_due_to_false_positive_risk"
        for item in editor._safe_auto_repair_candidates
    )
    assert not editor._is_high_confidence_chinese_fragment_candidate("哦，绝对是历史性的。")
    assert not editor._is_high_confidence_chinese_fragment_candidate("因为这两家公司主导了内存芯片市场。")


def test_safe_auto_repair_guard_rejects_repairs_that_create_new_hard_problem():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg("First different sentence.", 0, 1800, "第一句中文。"),
        ASRDataSeg("Second different sentence.", 1800, 3600, "第二句中文。"),
    ]
    for index, seg in enumerate(segments, 1):
        seg.subtitle_id = f"S{index:04d}"
    damaged = [editor._copy_segment(seg) for seg in segments]
    damaged[1] = editor._copy_segment(damaged[1], translated_text="第一句中文。")

    with patch.object(editor, "_repair_exact_duplicate_chinese_segments", return_value=damaged):
        repaired = editor._safe_auto_repair_segments(segments, stage="test")

    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]
    assert any(item["code"] == "safe_repair_guard_rejected" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_repairs_high_confidence_chinese_candidate_after_final_alignment():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [ASRDataSeg("Yeah, he is out there.", 0, 1800, "是啊，他正在")]
    segments[0].subtitle_id = "S0001"
    item = ScreenSubtitleItem(
        source_ids=[1],
        original=segments[0].text,
        translated=segments[0].translated_text,
        subtitle_id="S0001",
    )
    semantic_groups = [{"id": 1, "start_index": 0, "items": [item]}]
    editor._last_semantic_full_translations = {1: "是啊，他正在外面积极行动。"}

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={
            "groups": [
                {
                "target_subtitle_id": "S0001",
                "segments": [{"subtitle_id": "S0001", "zh": "是啊，他正在外面积极行动。"}],
                }
            ]
        },
    ) as request:
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=[item],
            stage="after_final_time_alignment",
        )

    assert request.called
    assert repaired[0].text == segments[0].text
    assert repaired[0].subtitle_id == "S0001"
    assert repaired[0].translated_text == "是啊，他正在外面积极行动。"
    assert any(item["code"] == "llm_chinese_candidate_repaired" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_does_not_run_candidate_repair_before_final_alignment():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    segments = [ASRDataSeg("Yeah, he is out there.", 0, 1800, "是啊，他正在")]
    segments[0].subtitle_id = "S0001"
    item = ScreenSubtitleItem(
        source_ids=[1],
        original=segments[0].text,
        translated=segments[0].translated_text,
        subtitle_id="S0001",
    )
    semantic_groups = [{"id": 1, "start_index": 0, "items": [item]}]
    editor._last_semantic_full_translations = {1: "是啊，他正在外面积极行动。"}

    with patch.object(editor, "_request_chinese_compression") as request:
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=[item],
            stage="before_export",
        )

    assert not request.called
    assert repaired[0].translated_text == segments[0].translated_text


def test_safe_auto_repair_llm_rejects_invalid_candidate_repair():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [ASRDataSeg("Yeah, he is out there.", 0, 1800, "是啊，他正在")]
    segments[0].subtitle_id = "S0001"
    item = ScreenSubtitleItem(
        source_ids=[1],
        original=segments[0].text,
        translated=segments[0].translated_text,
        subtitle_id="S0001",
    )
    semantic_groups = [{"id": 1, "start_index": 0, "items": [item]}]
    editor._last_semantic_full_translations = {1: "是啊，他正在外面积极行动。"}

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={
            "groups": [
                {
                "target_subtitle_id": "S0001",
                "segments": [{"subtitle_id": "S0001", "zh": "因为"}],
                }
            ]
        },
    ):
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=[item],
            stage="after_final_time_alignment",
        )

    assert repaired[0].translated_text == segments[0].translated_text
    assert any(item["code"] == "llm_chinese_candidate_repair_rejected" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_retries_invalid_candidate_with_same_group_context():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg("when you look at internet native humor and culture.", 0, 2600, "当你在看网络原生幽默和文化时。"),
        ASRDataSeg("Zachary Dunn is a fascinating example.", 2600, 5200, "Zachary Dunn就是一个很有意思的例子。"),
    ]
    for index, segment in enumerate(segments, 1):
        segment.subtitle_id = f"S{index:04d}"
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=segment.text,
            translated=segment.translated_text,
            subtitle_id=segment.subtitle_id,
        )
        for index, segment in enumerate(segments, 1)
    ]
    semantic_groups = [{"id": 1, "start_index": 0, "items": items}]
    editor._last_semantic_full_translations = {
        1: "从网络原生幽默和文化来看，Zachary Dunn就是一个很有意思的例子。"
    }

    responses = [
        {
            "groups": [
                {
                "target_subtitle_id": "S0001",
                "segments": [{"subtitle_id": "S0001", "zh": "因为"}],
                }
            ]
        },
        {
            "groups": [
                {
                "target_subtitle_id": "S0001",
                "segments": [
                    {"subtitle_id": "S0001", "zh": "从网络原生幽默和文化来看，"},
                    {"subtitle_id": "S0002", "zh": "Zachary Dunn就是一个很有意思的例子。"},
                    ],
                }
            ]
        },
    ]

    def fake_request(*args, **kwargs):
        return responses.pop(0)

    with patch.object(editor, "_request_chinese_compression", side_effect=fake_request) as request:
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
            stage="after_final_time_alignment",
        )

    assert request.call_count == 2
    assert [seg.text for seg in repaired] == [seg.text for seg in segments]
    assert [seg.subtitle_id for seg in repaired] == ["S0001", "S0002"]
    assert repaired[0].translated_text == "从网络原生幽默和文化来看，"
    assert repaired[1].translated_text == segments[1].translated_text
    assert any(item["code"] == "llm_chinese_candidate_repaired" for item in editor._safe_auto_repair_log)


def test_safe_auto_repair_llm_rejects_new_adjacent_chinese_boundary_break():
    editor = _id_editor()
    editor.enable_safe_auto_repair = True
    editor._safe_auto_repair_log = []
    segments = [
        ASRDataSeg(
            "You validate a radically new disruptive movement by anchoring it",
            466020,
            469660,
            "你将一个全新的颠覆性运动，直接锚定在",
        ),
        ASRDataSeg(
            "directly to an ancient, established, and highly respected text.",
            469700,
            473600,
            "一部古老、权威且备受尊崇的文本上，从而为其提供合法性。",
        ),
    ]
    for index, segment in enumerate(segments, 1):
        segment.subtitle_id = f"S{index:04d}"
    items = [
        ScreenSubtitleItem(
            source_ids=[index],
            original=segment.text,
            translated=segment.translated_text,
            subtitle_id=segment.subtitle_id,
        )
        for index, segment in enumerate(segments, 1)
    ]
    semantic_groups = [{"id": 1, "start_index": 0, "items": items}]
    editor._last_semantic_full_translations = {
        1: "你将一个全新的颠覆性运动，直接锚定在一部古老、权威且备受尊崇的文本上，从而为其提供合法性。"
    }

    with patch.object(
        editor,
        "_request_chinese_compression",
        return_value={
            "groups": [
                {
                "target_subtitle_id": "S0001",
                "segments": [
                    {"subtitle_id": "S0001", "zh": "你将一个全新的颠覆性运动，直接锚定它"},
                    {"subtitle_id": "S0002", "zh": "到一部古老、权威且备受尊崇的文本上，从而为其提供合法性。"},
                    ],
                }
            ]
        },
    ):
        repaired = editor._safe_auto_repair_segments(
            segments,
            semantic_groups=semantic_groups,
            subtitle_items=items,
            stage="after_final_time_alignment",
        )

    assert [seg.translated_text for seg in repaired] == [seg.translated_text for seg in segments]
    assert any(item["code"] == "llm_chinese_candidate_repair_rejected" for item in editor._safe_auto_repair_log)


def test_final_gate_blocks_protected_named_phrase_split():
    editor = _marker_editor(["Wall", "Street", "is", "watching"], max_words=8)
    items = [_word_item(editor, 0, 0, 1), _word_item(editor, 1, 3, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == ["Wall Street is watching"]
    assert "protected_named_phrase_split" in editor._syntax_boundary_reasons("Wall", "Street is watching")


def test_final_gate_blocks_protected_phrasal_boundary_split():
    editor = _marker_editor(["They", "are", "pricing", "in", "the", "belief"], max_words=8)
    items = [_word_item(editor, 0, 2, 1), _word_item(editor, 3, 5, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == ["They are pricing in the belief"]
    assert "protected_phrasal_boundary_split" in editor._syntax_boundary_reasons("They are pricing", "in the belief")


def test_final_gate_blocks_look_at_boundary_split():
    editor = _marker_editor(["We", "need", "to", "look", "at", "why", "this", "changed"], max_words=8)
    items = [_word_item(editor, 0, 3, 1), _word_item(editor, 4, 7, 2)]

    repaired = editor._validate_and_repair_final_pre_id_boundaries(items)

    assert [item.original for item in repaired] == ["We need to look at why this changed"]
    assert "protected_phrasal_boundary_split" in editor._syntax_boundary_reasons("We need to look", "at why this changed")


def test_passed_validation_writes_final_output_and_manifest_metadata():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample.m4a"
        audio_path.write_bytes(b"audio")
        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "这是译文")]),
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="passed",
            manifest_meta={
                "translation_model": "deepseek-v4-flash",
                "code_commit": "abc123",
                "cache_used": False,
                "prompt_version": "global-subtitle-id-v2",
            },
        )

        manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["render_blocked"] is False
        assert manifest["translation_model"] == "deepseek-v4-flash"
        assert manifest["code_commit"] == "abc123"
        assert manifest["cache_used"] is False
        assert manifest["prompt_version"] == "global-subtitle-id-v2"
        assert (output_dir / "output.srt").exists()
        assert not (output_dir / "字幕处理结果摘要.txt").exists()
        result_dir = source_dir / "sample-处理结果"
        summary_path = result_dir / "质检报告" / "字幕处理结果摘要.txt"
        assert summary_path.exists()
        summary = summary_path.read_text(encoding="utf-8-sig")
        assert "结论：通过" in summary
        assert "字幕数量：1" in summary
        assert all(
            Path(path).parent == result_dir / "字幕文件"
            for path in manifest["source_subtitle_paths"].values()
        )


def test_stable_result_summary_records_safe_repair_details():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample.m4a"
        audio_path.write_bytes(b"audio")
        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "这是译文")]),
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="passed",
            validation_summary={"status": "WARNING", "errors": [], "warnings": [{"code": "x", "message": "待检查"}], "info": []},
            manifest_meta={
                "safe_auto_repair_enabled": True,
                "safe_auto_repair_log": [
                    {
                        "code": "llm_chinese_candidate_repaired",
                        "subtitle_id": "S0001",
                        "start": "00:00:00.000",
                        "end": "00:00:01.000",
                        "before_chinese": "旧中文",
                        "after_chinese": "新中文",
                    }
                ],
                "safe_auto_repair_candidates": [{"code": "candidate"}],
            },
        )

        manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert "work_summary_txt" not in manifest["result_summary_paths"]
        summary_path = Path(manifest["result_summary_paths"]["source_summary_txt"])
        summary = summary_path.read_text(encoding="utf-8-sig")
        assert "结论：可用" in summary
        assert "实际修复：1" in summary
        assert "旧中文" in summary
        assert "新中文" in summary


def test_qa_review_srt_is_not_mirrored_to_source_audio_folder():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample.m4a"
        audio_path.write_bytes(b"audio")
        coverage_path = output_dir / "output-coverage-report.txt"
        coverage_path.write_text("coverage", encoding="utf-8")
        qa_path = output_dir / "qa-review-points.srt"
        qa_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nQA\n", encoding="utf-8")

        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English 1.", 0, 1000, "译文")]),
            config,
            coverage_report_path=str(coverage_path),
            validation_status="passed",
            manifest_meta={"qa_review_points_srt": str(qa_path)},
        )

        assert qa_path.exists()
        assert not (source_dir / "qa-review-points.srt").exists()
        assert not (source_dir / "coverage-report.txt").exists()
        assert not (source_dir / "stable-final-manifest.json").exists()

        work_manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert work_manifest["qa_review_points_srt"] == str(qa_path)
        assert "source_report_paths" not in work_manifest


def test_user_subtitle_exports_are_saved_to_media_result_folder():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        output_dir = root / "work" / "subtitle"
        source_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        audio_path = source_dir / "sample-audio.m4a"
        audio_path.write_bytes(b"audio")

        task = SubtitleTask(
            subtitle_path=str(output_dir / "source.srt"),
            video_path=str(audio_path),
            output_path=str(output_dir / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="translation_top",
        )

        thread._save_stable_subtitle_outputs(
            ASRData([ASRDataSeg("English line.", 0, 1000, "中文行。")]),
            config,
            validation_status="passed",
        )

        result_dir = source_dir / "sample-audio-处理结果"
        subtitle_dir = result_dir / "字幕文件"
        bilingual = subtitle_dir / "双语字幕.srt"
        named_bilingual = subtitle_dir / "sample-audio-原文在上双语字幕.srt"
        chinese = subtitle_dir / "中文字幕.srt"
        english = subtitle_dir / "英文字幕.srt"
        assert bilingual.exists()
        assert named_bilingual.exists()
        assert chinese.exists()
        assert english.exists()
        bilingual_text = bilingual.read_text(encoding="utf-8-sig")
        assert named_bilingual.read_text(encoding="utf-8-sig") == bilingual_text
        assert "English line.\n中文行。" in bilingual_text
        assert "中文行。" in chinese.read_text(encoding="utf-8-sig")
        assert "English line." not in chinese.read_text(encoding="utf-8-sig")
        assert "English line." in english.read_text(encoding="utf-8-sig")
        assert "中文行。" not in english.read_text(encoding="utf-8-sig")

        manifest = json.loads((output_dir / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_subtitle_paths"] == {
            "bilingual_original_top_srt": str(bilingual),
            "named_bilingual_original_top_srt": str(named_bilingual),
            "only_translation_srt": str(chinese),
            "only_original_srt": str(english),
        }


def test_screen_manifest_metadata_includes_stage_timings():
    class FakeScreenEditor:
        @staticmethod
        def manifest_metadata():
            return {"translation_model": "deepseek-v4-flash"}

    thread = SubtitleThread.__new__(SubtitleThread)
    thread._stage_timings_seconds = {"screen_subtitle_edit": 12.345, "final_subtitle_save": 0.5}

    metadata = thread._screen_manifest_metadata(FakeScreenEditor())

    assert metadata["translation_model"] == "deepseek-v4-flash"
    assert metadata["stage_timings_seconds"]["screen_subtitle_edit"] == 12.345
    assert metadata["stage_timings_total_seconds"] == 12.845


def test_id_bound_mapping_has_no_drift_over_400_subtitles():
    editor = _id_editor()
    items = editor._assign_global_subtitle_ids(_id_items(405))
    group = _id_group(1, 0, items)
    translations = editor._parse_id_bound_translations(
        group,
        editor._group_expected_subtitle_ids(group),
        [
            {"subtitle_id": item.subtitle_id, "zh": f"zh-{item.subtitle_id}"}
            for item in reversed(items)
        ],
    )
    applied = editor._apply_semantic_group_translations(items, [group], {1: translations})
    editor._validate_final_item_translation_ids(applied)

    assert editor._translation_structure_errors == []
    assert [item.subtitle_id for item in applied] == [item.subtitle_id for item in items]
    assert [item.original for item in applied] == [item.original for item in items]
    assert [item.word_start for item in applied] == [item.word_start for item in items]
    assert applied[-1].translated == "zh-S0405"


def test_validation_summary_error_writes_failure_without_publishing_manifest():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        task = SubtitleTask(
            subtitle_path=str(root / "source.srt"),
            output_path=str(root / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )
        data = ASRData([ASRDataSeg("Really?", 0, 100, "ok")])
        summary = {
            "status": "ERROR",
            "errors": [{"code": "subtitle_duration_invalid"}],
            "warnings": [],
            "info": [],
        }

        thread._save_stable_subtitle_outputs(
            data,
            config,
            coverage_report_path=str(root / "coverage-report.txt"),
            validation_status="passed",
            validation_summary=summary,
        )

        failure = json.loads((root / "stable-last-failure.json").read_text(encoding="utf-8"))
        assert failure["validation_status"] == "failed"
        assert failure["render_blocked"] is True
        assert failure["validation_error_codes"] == ["subtitle_duration_invalid"]
        assert not (root / "stable-final-manifest.json").exists()
        assert not (root / "stable-final-original-top.srt").exists()
        assert not (root / "output.srt").exists()


def test_review_only_validation_error_publishes_stable_outputs():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        task = SubtitleTask(
            subtitle_path=str(root / "source.srt"),
            output_path=str(root / "output.srt"),
        )
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = task
        config = SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )
        data = ASRData([ASRDataSeg("This is short.", 0, 1500, "这条中文字幕阅读速度偏快。")])
        summary = {
            "status": "ERROR",
            "errors": [{"code": "reading_speed_error"}],
            "warnings": [],
            "info": [],
            "review": {
                "schema_version": 2,
                "summary": {
                    "blocker_count": 0,
                    "review_count": 1,
                    "info_count": 0,
                    "actionable_count": 1,
                },
                "items": [
                    {
                        "severity": "REVIEW",
                        "source_level": "error",
                        "code": "reading_speed_error",
                    },
                    {
                        "severity": "BLOCKER",
                        "source_level": "allocation_quality",
                        "code": "allocation_quality_unresolved",
                    },
                ],
            },
        }

        assert not SubtitleThread._stable_validation_summary_blocks_render(summary)
        thread._save_stable_subtitle_outputs(
            data,
            config,
            validation_status="passed",
            validation_summary=summary,
        )

        manifest = json.loads((root / "stable-final-manifest.json").read_text(encoding="utf-8"))
        assert manifest["render_blocked"] is False
        assert manifest["validation_summary"]["errors"][0]["code"] == "reading_speed_error"
        assert not (root / "stable-last-failure.json").exists()
        assert (root / "stable-final-original-top.srt").exists()
        assert (root / "output.srt").exists()


def test_validation_blocker_severity_and_legacy_error_still_block_render():
    blocker_summary = {
        "status": "ERROR",
        "errors": [{"code": "final_cue_timeline_invalid"}],
        "review": {"summary": {"blocker_count": 1}},
    }
    legacy_error_summary = {
        "status": "ERROR",
        "errors": [{"code": "unknown_legacy_error"}],
    }

    assert SubtitleThread._stable_validation_summary_blocks_render(blocker_summary)
    assert SubtitleThread._stable_validation_summary_blocks_render(legacy_error_summary)


def test_runtime_module_import_path_is_available():
    result = subprocess.run(
        [str(ROOT / "runtime" / "python.exe"), "-m", "tests.caption_audit.run_all", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0
    assert "Audit stable bilingual subtitle outputs" in result.stdout


def test_whisperx_alignment_mapping_preserves_source_tokens_and_local_fallback():
    source = [
        ASRDataSeg("A", 100, 200),
        ASRDataSeg("56-year-old", 200, 400),
        ASRDataSeg("speaker,", 400, 600),
        ASRDataSeg("continues.", 600, 800),
    ]
    aligned_words = [
        {"text": "A", "start": 0.12, "end": 0.22},
        {"text": "speaker", "start": 0.42, "end": 0.62},
        {"text": "continues", "start": 0.64, "end": 0.88},
    ]

    mapped = _make_whisperx_word_segments(source, aligned_words)

    assert [seg.text for seg in mapped.segments] == [seg.text for seg in source]
    assert [seg.start_time for seg in mapped.segments] == [120, 200, 420, 640]
    assert [seg.end_time for seg in mapped.segments] == [220, 400, 620, 880]


def test_whisperx_expansion_compression_fallback_is_local_and_opt_in():
    """A compact numeral must not pull later spoken words ahead of their ledger span."""
    source = [
        ASRDataSeg("53", 412600, 413240),
        ASRDataSeg("billion", 413240, 413900),
        ASRDataSeg("to", 413900, 414500),
        ASRDataSeg("AI", 414500, 414800),
        ASRDataSeg("between", 414800, 415260),
        ASRDataSeg("2026", 415260, 416100),
        ASRDataSeg("and", 416100, 416400),
        ASRDataSeg("2028", 416400, 417020),
        ASRDataSeg("Now", 417240, 417700),
    ]
    aligned_words = [
        {"text": "53", "start": 412.677, "end": 412.737},
        {"text": "billion", "start": 412.757, "end": 412.977},
        {"text": "to", "start": 412.997, "end": 413.097},
        {"text": "AI", "start": 413.137, "end": 413.197},
        {"text": "between", "start": 413.217, "end": 413.358},
        {"text": "2026", "start": 413.578, "end": 413.818},
        {"text": "and", "start": 413.878, "end": 413.978},
        {"text": "2028", "start": 413.998, "end": 414.218},
        {"text": "Now", "start": 417.580, "end": 417.720},
    ]

    default_mapped = _make_whisperx_word_segments(source, aligned_words)
    assert default_mapped.whisperx_expansion_fallbacks == []
    assert all(segment.alignment_source == "whisperx" for segment in default_mapped.segments)

    alignment_source = ASRData(
        [ASRDataSeg("53 billion to AI between 2026 and 2028. Now", 412600, 417700)]
    )
    with patch(
        "app.core.subtitle_processor.stable_ts_alignment._run_whisperx_words",
        return_value=aligned_words,
    ):
        mapped = align_frozen_word_ledger_with_whisperx(
            "unused.m4a",
            alignment_source,
            ASRData(source),
        )

    assert mapped is not None
    assert [(segment.word_id, segment.text) for segment in mapped.segments] == list(
        enumerate([segment.text for segment in source])
    )
    for index in range(8):
        assert (mapped.segments[index].start_time, mapped.segments[index].end_time) == (
            source[index].start_time,
            source[index].end_time,
        )
        assert mapped.segments[index].alignment_source == "stable-ts-fallback"
    assert (mapped.segments[8].start_time, mapped.segments[8].end_time) == (417580, 417720)
    assert mapped.segments[8].alignment_source == "whisperx"
    assert mapped.whisperx_fallback_word_count == 8
    assert mapped.whisperx_expansion_fallbacks == [
        {
            "code": "whisperx_expansion_compression_fallback",
            "trigger_word_id": 0,
            "trigger_word": "53",
            "fallback_word_ids": list(range(8)),
            "baseline_range_ms": [412600, 417020],
            "rejected_whisperx_range_ms": [412677, 414218],
        }
    ]


def test_whisperx_numeric_pause_collapse_restores_delayed_percentage_boundary():
    """WhisperX must not stretch the prior word across a trusted numeric pause."""
    source = [
        ASRDataSeg("app", 500, 740),
        ASRDataSeg("field,", 740, 1080),
        ASRDataSeg("73%", 1560, 2500),
        ASRDataSeg("of", 2500, 2700),
    ]
    aligned_words = [
        {"text": "app", "start": 0.520, "end": 0.760},
        {"text": "field", "start": 0.801, "end": 2.001},
        {"text": "73%", "start": 2.041, "end": 2.722},
        {"text": "of", "start": 2.762, "end": 2.942},
    ]

    mapped = _make_whisperx_word_segments(
        source,
        aligned_words,
        reject_expansion_drift=True,
    )

    assert [
        (segment.start_time, segment.end_time, segment.alignment_source)
        for segment in mapped.segments
    ] == [
        (520, 760, "whisperx"),
        (740, 1080, "stable-ts-fallback"),
        (1560, 2500, "stable-ts-fallback"),
        (2762, 2942, "whisperx"),
    ]
    assert mapped.whisperx_expansion_fallbacks == [
        {
            "code": "whisperx_expansion_pause_fallback",
            "trigger_word_id": 2,
            "trigger_word": "73%",
            "fallback_word_ids": [1, 2],
            "baseline_pause_ms": 480,
            "rejected_whisperx_pause_ms": 40,
            "effective_onset_delay_ms": 481,
        }
    ]


def test_whisperx_numeric_pause_collapse_restores_prior_word_when_number_is_unmatched():
    """An unmatched percentage must not be delayed by the prior WhisperX word."""
    source = [
        ASRDataSeg("first", 551600, 551800),
        ASRDataSeg("move.", 551800, 552000),
        ASRDataSeg("72%.", 552420, 552940),
        ASRDataSeg("Why", 552940, 553180),
    ]
    aligned_words = [
        {"text": "first", "start": 551.620, "end": 551.820},
        {"text": "move", "start": 551.820, "end": 552.595},
        # WhisperX did not return the compact written-form percentage.
        {"text": "Why", "start": 552.960, "end": 553.200},
    ]

    mapped = _make_whisperx_word_segments(
        source,
        aligned_words,
        reject_expansion_drift=True,
    )

    assert (mapped.segments[1].start_time, mapped.segments[1].end_time) == (
        551800,
        552000,
    )
    assert mapped.segments[1].alignment_source == "stable-ts-fallback"
    assert (mapped.segments[2].start_time, mapped.segments[2].end_time) == (
        552420,
        552940,
    )
    assert mapped.whisperx_expansion_fallbacks == [
        {
            "code": "whisperx_expansion_pause_fallback",
            "trigger_word_id": 2,
            "trigger_word": "72%.",
            "fallback_word_ids": [1],
            "baseline_pause_ms": 420,
            "rejected_whisperx_pause_ms": -175,
            "effective_onset_delay_ms": 175,
        }
    ]


def test_whisperx_numeric_pause_guard_keeps_corroborated_local_shift():
    source = [
        ASRDataSeg("field,", 740, 1080),
        ASRDataSeg("73%", 1560, 2500),
    ]
    aligned_words = [
        {"text": "field", "start": 1.140, "end": 1.740},
        {"text": "73%", "start": 1.960, "end": 2.900},
    ]

    mapped = _make_whisperx_word_segments(
        source,
        aligned_words,
        reject_expansion_drift=True,
    )

    assert mapped.whisperx_expansion_fallbacks == []
    assert all(segment.alignment_source == "whisperx" for segment in mapped.segments)


def test_whisperx_plain_word_density_fallback_is_local():
    words = "does this all mean for you we're stuck".split()
    source = [
        ASRDataSeg(word, 1077000 + index * 240, 1077180 + index * 240)
        for index, word in enumerate(words)
    ]
    aligned_words = [
        {
            "text": word,
            "start": 1077.860 + index * 0.015,
            "end": 1078.601,
        }
        for index, word in enumerate(words)
    ]

    mapped = _make_whisperx_word_segments(source, aligned_words)

    assert mapped.word_timing_trust_issues == []
    assert mapped.whisperx_density_fallbacks == [
        {
            "code": "whisperx_implausible_word_density_fallback",
            "fallback_word_ids": list(range(len(words))),
            "rejected_whisperx_range_ms": [1077860, 1078601],
        }
    ]
    assert [
        (segment.start_time, segment.end_time, segment.alignment_source)
        for segment in mapped.segments
    ] == [
        (segment.start_time, segment.end_time, "stable-ts-fallback")
        for segment in source
    ]


def test_stable_ts_plain_word_density_fallback_keeps_valid_native_times():
    words = "So what does this all mean for you We're looking".split()
    source = [
        ASRDataSeg(word, 1075600 + index * 220, 1075780 + index * 220)
        for index, word in enumerate(words)
    ]
    aligned = [
        ASRDataSeg(word, segment.start_time, segment.end_time)
        for word, segment in zip(words, source)
    ]
    for index in range(2, 10):
        aligned[index].start_time = 1077980 + (index - 2) * 10
        aligned[index].end_time = 1078100

    fallbacks = _fallback_implausible_stable_ts_updates(
        source,
        aligned,
        source_timing_trusted=True,
    )

    assert fallbacks
    assert [
        (segment.start_time, segment.end_time)
        for segment in aligned
    ] == [
        (segment.start_time, segment.end_time)
        for segment in source
    ]
    assert find_implausible_word_timing_runs(aligned) == []


def test_stable_ts_density_fallback_rejects_an_implausible_native_baseline():
    words = "does this all mean for you we're stuck".split()
    source = [
        ASRDataSeg(word, 1077980 + index * 10, 1078100)
        for index, word in enumerate(words)
    ]
    aligned = [
        ASRDataSeg(word, segment.start_time, segment.end_time)
        for word, segment in zip(words, source)
    ]

    fallbacks = _fallback_implausible_stable_ts_updates(
        source,
        aligned,
        source_timing_trusted=True,
    )

    assert fallbacks == []
    assert find_implausible_word_timing_runs(aligned)


def test_stable_ts_density_fallback_stops_on_an_unmappable_empty_token():
    words = ["", "this", "all", "mean", "for", "you", "right", "now"]
    source = [
        ASRDataSeg(word, 1000 + index * 220, 1180 + index * 220)
        for index, word in enumerate(words)
    ]
    aligned = [
        ASRDataSeg(word, 2000, 2120)
        for word in words
    ]

    fallbacks = _fallback_implausible_stable_ts_updates(
        source,
        aligned,
        source_timing_trusted=True,
    )

    assert fallbacks == []
    assert find_implausible_word_timing_runs(aligned)


if __name__ == "__main__":
    test_formal_boundary_audit_projects_display_pages_and_unresolved_pre_id_evidence()
    test_stable_chinese_cache_rejects_stale_frozen_boundary_context()
    test_semantic_full_translation_rejects_duplicate_request_group_ids()
    test_allocation_payload_rejects_duplicate_group_ids()
    test_translation_api_only_retries_only_rate_limit_and_respects_budget()
    test_display_page_api_only_returns_attempts_without_worker_state_writes()
    test_semantic_full_translation_cache_survives_allocation_algorithm_change()
    test_semantic_full_translation_reads_verified_legacy_role_cache_once()
    test_semantic_cache_identity_uses_only_the_request_owner_model()
    test_invalid_full_translation_cache_is_replaced_only_by_valid_response()
    test_partial_full_translation_cache_preserves_valid_groups_for_resume()
    test_full_translation_unit_cache_invalidates_only_context_dependents()
    test_final_allocation_unit_cache_resumes_without_batch_request()
    test_llm_request_ledger_persists_token_and_reasoning_usage()
    test_invalid_allocation_cache_is_replaced_only_after_id_validation()
    test_final_time_alignment_reapplies_display_padding_to_loaded_short_subtitle()
    test_final_time_alignment_shifts_next_when_loaded_short_has_no_gap()
    test_final_time_alignment_runs_chinese_speed_repair_without_touching_english()
    test_fixed_id_parent_chinese_sync_updates_only_the_chinese_projection()
    test_fixed_id_parent_chinese_sync_rejects_structural_drift_before_writing()
    test_final_time_alignment_publishes_punctuation_repair_to_fixed_id_items()
    test_screen_editor_uses_16_word_stable_hard_floor()
    test_screen_editor_routes_full_translation_and_allocation_models_by_role()
    test_screen_editor_disables_sdk_level_retries()
    test_screen_manifest_records_translation_model_roles_and_retry_owners()
    test_stable_screen_pipeline_requests_word_timestamps_without_legacy_split()
    test_stable_screen_mode_skips_legacy_llm_optimization()
    test_stable_screen_mode_rejects_missing_or_unmappable_word_ledger()
    test_preposition_phrase_is_not_stranded()
    test_number_and_policy_sentence_keeps_readable_boundaries()
    test_long_finance_sentence_keeps_full_coverage()
    test_missing_translation_is_reported_but_not_blocking()
    test_suspicious_cut_is_warning_not_blocking()
    test_abnormal_timing_gap_is_repaired_for_compressed_cluster()
    test_coverage_gap_does_not_sum_natural_pauses()
    test_coverage_gap_blocks_single_long_uncovered_span()
    test_final_display_coverage_audit_preserves_timeline_chaining()
    test_final_display_coverage_audit_reports_long_gap_without_retiming()
    test_final_display_coverage_audit_reports_real_word_pause_without_retiming()
    test_final_time_alignment_keeps_final_timeline_chaining()
    test_chinese_reading_speed_error_is_reported_but_not_blocking()
    test_near_threshold_chinese_speed_is_a_warning_not_a_render_error()
    test_validation_report_adds_actionable_review_tiers_without_changing_status()
    test_validation_review_includes_allocation_unresolved_without_old_error_mutation()
    test_allocation_isolation_report_passes_when_only_chinese_changes()
    test_allocation_isolation_report_fails_on_english_boundary_change()
    test_duplicate_chinese_is_warning_not_blocking()
    test_repeated_english_with_repeated_chinese_is_not_a_duplicate_warning()
    test_overlong_english_segment_is_locally_split_without_llm()
    test_audit_parser_does_not_count_chinese_line_with_it_as_english()
    test_888_chinese_speed_compression_rejects_dangling_fragment()
    test_888_chinese_speed_compression_uses_semantic_group_context()
    test_000_group_validation_rejects_lost_ponder_action()
    test_444_independent_syntax_boundary_audit_catches_bad_cuts()
    test_syntax_boundary_audit_ignores_safe_short_dialogue()
    test_syntax_boundary_audit_keeps_confirmed_bad_cuts()
    test_chinese_semantic_group_audit_warns_on_lost_core_action()
    test_chinese_semantic_audit_skips_semantic_loss_when_mapping_invalid()
    test_chinese_semantic_audit_ignores_normal_short_responses()
    test_allocation_validator_retries_multi_signal_chinese_boundary_issue()
    test_semantic_audit_context_requires_id_signature_and_expected_ids()
    test_semantic_audit_mapping_does_not_shift_when_audit_groups_exceed_generation_count()
    test_semantic_audit_mapping_does_not_shift_when_audit_groups_drop_generation_count()
    test_repeated_short_dialogue_does_not_map_to_wrong_semantic_group()
    test_missing_semantic_group_id_only_invalidates_that_group()
    test_identical_english_but_different_subtitle_ids_do_not_match()
    test_g0248_full_translation_can_be_retraced_from_generated_context()
    test_validation_report_full_translation_uses_single_stage_raw_records_for_all_valid_groups()
    test_mapping_failure_does_not_emit_full_translation_dependent_false_positive()
    test_command_chinese_audit_catches_confirmed_bad_groups()
    test_command_chinese_audit_ignores_normal_short_groups()
    test_very_short_subtitle_has_dedicated_duration_error()
    test_short_backchannel_duration_is_warning_not_error()
    test_short_regular_sentence_duration_remains_error()
    test_asr_suspicious_phrases_are_reported_without_fixing_text()
    test_asr_suspicious_article_context_misses_are_reported()
    test_asr_suspicious_issues_are_bound_to_frozen_subtitle_ids()
    test_abbreviation_name_boundary_is_syntax_warning()
    test_terminal_punctuation_wins_over_token_only_determiner_heuristic()
    test_pronoun_restart_is_not_misclassified_as_a_determiner_head_split()
    test_spaced_initialism_period_does_not_split_a_continuing_clause()
    test_spaced_initialism_can_end_a_sentence_with_capitalized_restart_and_pause()
    test_pronominal_appositive_prefers_the_complete_referent_at_an_alternative_cut()
    test_caption_audit_uses_16_word_hard_limit()
    test_caption_audit_accepts_allowed_plus_discourse_overflow()
    test_caption_audit_treats_borderline_chinese_speed_as_warning_not_blocker()
    test_caption_audit_uses_the_runtime_chinese_speed_error_boundary()
    test_caption_audit_keeps_numeric_percent_chinese_line()
    test_large_number_anchor_variants_do_not_crash()
    test_concise_group_allocation_is_not_rejected_by_coverage_only()
    test_final_time_alignment_checks_chinese_speed_against_final_timeline_duration()
    test_chinese_compression_inherits_terminal_punctuation()
    test_chinese_compression_accepts_punctuated_sentence_outside_action_whitelist()
    test_single_cue_speed_compression_does_not_use_allocation_coverage_as_a_veto()
    test_short_but_severe_chinese_speed_triggers_repair()
    test_borderline_chinese_speed_does_not_trigger_render_blocker()
    test_short_subtitle_gets_minimum_display_duration_when_room_allows()
    test_short_backchannel_merges_with_following_segment()
    test_short_sentence_bridges_small_gap_before_next_subtitle()
    test_standalone_discourse_marker_attaches_to_immediate_next_sentence()
    test_attached_oh_and_then_lead_in_merges_with_contiguous_clause()
    test_question_oh_lead_in_remains_independent()
    test_oh_and_then_lead_in_respects_long_pause()
    test_oh_and_then_lead_in_respects_speaker_change()
    test_plus_marker_keeps_a_complete_one_word_overflow_unit()
    test_oh_marker_attaches_to_next_complete_unit_at_one_word_overflow()
    test_trailing_standalone_discourse_marker_attaches_to_previous_sentence()
    test_standalone_discourse_marker_does_not_cross_long_pause()
    test_standalone_discourse_marker_does_not_cross_speaker_change()
    test_overlong_discourse_marker_attachment_reselects_cutpoint()
    test_discourse_marker_rebalance_does_not_leave_one_word_fragment()
    test_trailing_discourse_marker_is_not_left_at_subtitle_end()
    test_discourse_marker_phrase_is_not_split_during_rebalance()
    test_trailing_discourse_marker_rebalances_two_long_items_without_word_loss()
    test_short_yeah_rebalances_with_long_following_sentence()
    test_short_though_attaches_to_following_sentence()
    test_short_though_rebalances_without_leaving_orphan()
    test_discourse_marker_ids_are_assigned_after_all_english_boundaries_are_fixed()
    test_discourse_marker_pre_id_pipeline_keeps_400_plus_english_chinese_id_sets_equal()
    test_discourse_marker_pre_id_pipeline_keeps_421_item_structure_errors_zero()
    test_balanced_split_does_not_create_preposition_object_boundary()
    test_determiner_numeric_noun_boundary_is_hard_illegal()
    test_quantifier_phrase_boundary_is_hard_illegal()
    test_adverb_adjective_boundary_is_hard_illegal_without_pause()
    test_short_verb_complement_boundary_is_hard_when_syntax_marks_it()
    test_short_verb_possessive_complement_boundary_is_hard_when_syntax_marks_it()
    test_parser_blocks_direct_verb_particle_boundary()
    test_parser_blocks_compact_coordinated_subject_boundary()
    test_parser_blocks_compact_coordination_boundaries()
    test_parser_blocks_object_content_clause_boundary()
    test_parser_blocks_object_attached_modifier_boundary()
    test_parser_keeps_clause_scope_adverb_with_following_subordinator()
    test_parser_clause_scope_modifier_guard_has_general_positive_and_negative_cases()
    test_parser_blocks_misattached_zero_relative_clause_boundary()
    test_parser_blocks_cross_cue_dependency_units_from_oil_run()
    test_parser_blocks_dreamcore_cross_cue_dependency_continuations()
    test_dreamcore_dependency_continuation_guard_respects_sentence_and_pause()
    test_cross_cue_dependency_guards_keep_independent_boundaries_legal()
    test_final_pre_id_repairs_oil_dependency_boundaries_without_word_loss()
    test_parser_blocks_clausal_subject_from_its_finite_predicate()
    test_parser_blocks_short_dative_object_start_boundary()
    test_parser_blocks_numeric_range_boundaries()
    test_parser_keeps_an_extended_numeric_range_attached_to_its_to_connector()
    test_pre_id_candidate_gate_rejects_new_hard_syntax_boundary()
    test_long_object_still_allows_legal_boundary()
    test_final_pre_id_repair_removes_known_hard_boundary()
    test_final_pre_id_blocks_content_noun_that_clause_boundary()
    test_final_pre_id_keeps_discourse_marker_with_following_sentence_after_terminal_over()
    test_final_pre_id_rebalances_leading_nonfinite_dependent_prefix()
    test_final_pre_id_keeps_finite_conditional_introduction_in_its_own_cue()
    test_leading_nonfinite_dependent_prefix_rebalance_respects_long_pause()
    test_leading_nonfinite_dependent_prefix_rebalance_respects_speaker_change()
    test_final_pre_id_repair_does_not_cross_speaker_change()
    test_final_pre_id_rejects_noop_repartition_without_iteration_loop()
    test_verb_directional_adverb_preposition_boundary_is_hard_when_syntax_marks_it()
    test_parser_dependency_phrase_entrances_are_hard_boundaries()
    test_dependency_phrase_entrance_guard_allows_independent_sentence_starts()
    test_parser_clause_chains_block_migrated_dependency_boundaries()
    test_pre_id_candidate_cannot_remove_existing_strong_sentence_anchor()
    test_migrated_dependency_guards_allow_independent_sentence_boundaries()
    test_short_display_merge_keeps_original_when_no_safe_boundary_exists()
    test_final_pre_id_preserves_word_order_coverage_and_timestamps()
    test_boundary_snapshot_payload_records_pre_id_repairs()
    test_subject_finite_verb_we_tend_is_hard_boundary()
    test_subject_finite_verb_they_needed_is_hard_boundary()
    test_subject_finite_verb_ai_is_upending_is_hard_boundary()
    test_modifier_head_actually_good_is_hard_boundary()
    test_relative_clause_subject_verb_you_can_is_hard_boundary()
    test_final_pre_id_repairs_yeah_so_todd_subject_fragment()
    test_final_pre_id_repairs_pronoun_only_fragment()
    test_final_pre_id_merges_high_confidence_fragment_into_unsplittable_19_word_sentence()
    test_final_pre_id_does_not_allow_fragment_merge_over_19_words()
    test_final_pre_id_does_not_allow_structural_merge_when_safe_cut_exists()
    test_final_pre_id_attaches_standalone_so_to_next_sentence()
    test_final_pre_id_keeps_independent_short_answers()
    test_weak_fragment_repair_does_not_cross_speaker_change()
    test_weak_fragment_repair_does_not_cross_long_pause()
    test_internal_transition_attaches_to_following_sentence()
    test_final_pre_id_repair_does_not_create_new_hard_issue()
    test_unresolved_weak_fragment_is_recorded_when_no_safe_repair()
    test_final_pre_id_second_phase_preserves_word_order_and_timestamps()
    test_boundary_snapshots_record_stage_changes_before_subtitle_ids()
    test_final_stable_english_boundaries_do_not_change_for_video_layout()
    test_final_gate_blocks_particle_preposition_complement_split()
    test_final_gate_keeps_preposition_object_boundary_illegal_after_long_pause()
    test_stable_cut_keeps_preposition_object_phrase_together_in_long_sentence()
    test_parser_confirmed_verb_object_boundary_stays_illegal_after_long_pause()
    test_parser_blocks_clause_introducer_from_ending_a_cue()
    test_parser_blocks_verb_from_its_preposition_complement()
    test_parser_blocks_verb_from_numeric_result_expression()
    test_parser_mapping_keeps_numeric_result_after_hyphenated_ledger_word()
    test_stable_cut_balances_the_full_sentence_instead_of_leaving_a_short_tail()
    test_stable_cut_does_not_evaluate_overflow_when_normal_partition_exists()
    test_final_fragment_blocks_short_open_prefix_but_allows_finite_clause()
    test_final_pre_id_repair_keeps_short_open_prefix_with_clause_across_pause()
    test_orphaned_predicate_parse_is_cached_for_the_same_frozen_span()
    test_final_gate_soft_flags_heuristic_short_verb_object_split()
    test_final_gate_blocks_auxiliary_predicate_split()
    test_final_gate_soft_flags_heuristic_catenative_verb_complement_split()
    test_final_gate_blocks_numeric_unit_or_noun_split()
    test_numeric_sentence_restart_after_long_pause_is_legal()
    test_punctuated_numeric_model_allows_a_determiner_clause_restart()
    test_numeric_unit_split_remains_hard_with_ordinary_pause()
    test_numeric_sentence_boundary_is_not_repaired_as_a_numeric_phrase()
    test_final_gate_soft_flags_heuristic_compound_noun_split()
    test_final_gate_soft_flags_heuristic_modifier_noun_head_split()
    test_final_gate_blocks_negation_emphasis_split()
    test_final_gate_blocks_stranded_leading_of_complement()
    test_final_gate_blocks_stranded_leading_with_complement()
    test_final_gate_blocks_time_range_to_continuation()
    test_final_gate_blocks_coordinated_modifier_split()
    test_final_gate_blocks_modifier_chain_split()
    test_final_gate_blocks_high_confidence_phrasal_verb_particle_split()
    test_final_fragment_gate_repairs_trailing_dependent_fragments()
    test_final_fragment_gate_repairs_possessive_and_quantifier_tails()
    test_final_gate_allows_sentence_initial_to_me_after_punctuation()
    test_final_fragment_gate_repairs_incomplete_interrogative_fragment()
    test_final_repair_does_not_create_adjacent_subject_fragment()
    test_final_repair_does_not_create_ordinary_one_word_fragment()
    test_final_fragment_gate_repairs_connector_and_reflexive_fragments()
    test_final_fragment_gate_records_unresolved_when_no_legal_solution()
    test_podcast_template_prefers_stable_manifest_subtitle()
    test_podcast_template_blocks_failed_stable_manifest_subtitle()
    test_podcast_template_does_not_fall_back_when_manifest_is_invalid_or_unusable()
    test_podcast_template_reuses_legacy_reading_speed_manifest_when_revalidated()
    test_podcast_template_preserves_full_media_duration_when_subtitles_end_early()
    test_podcast_template_uses_frozen_task_configuration()
    test_podcast_english_only_mode_hides_only_chinese_subtitle_for_both_templates()
    test_article_cover_renders_unmasked_date_and_preserves_empty_opt_out()
    test_article_brand_logo_is_optional_and_preserves_aspect_ratio()
    test_article_brand_logo_rejects_missing_or_unreadable_files()
    test_article_opening_title_shrinks_to_keep_a_normal_long_title_in_three_lines()
    test_article_opening_title_wraps_on_chinese_word_boundaries()
    test_article_opening_title_preserves_explicit_line_breaks_and_uses_heavy_font()
    test_article_opening_title_accent_matches_the_visible_title_height()
    test_article_template_uses_full_hd_canvas_and_balanced_subtitle_widths()
    test_caption_wrapper_never_orphans_a_leading_connector_to_balance_two_lines()
    test_caption_wrapper_preserves_preposition_and_infinitive_phrase_edges()
    test_caption_wrapper_distinguishes_complete_phrase_starts_from_stranded_dependencies()
    test_caption_wrapper_accepts_a_complete_article_bearing_prepositional_phrase()
    test_caption_wrapper_scales_before_breaking_a_hyphenated_compound()
    test_caption_wrapper_does_not_mistake_finite_ed_verb_for_modifier()
    test_article_page_planner_does_not_mistake_ment_noun_for_ent_modifier()
    test_caption_wrapper_accepts_a_complete_terminal_relative_clause()
    test_article_page_accepts_terminal_pronoun_and_phrasal_preposition()
    test_article_template_does_not_truncate_a_long_english_subtitle()
    test_article_template_keeps_full_chinese_for_structural_overflow_cue()
    test_article_page_timeline_uses_fixed_fonts_and_word_boundaries()
    test_stable_display_planner_is_deterministic_and_covers_each_word_once()
    test_stable_display_planner_keeps_legality_separate_from_large_soft_cost()
    test_stable_display_planner_minimizes_risk_before_visual_cost()
    test_article_renderer_never_accepts_a_forbidden_line_break_in_a_long_cue()
    test_article_renderer_keeps_short_default_cue_on_comfortable_static_profile()
    test_article_renderer_keeps_readable_two_line_cue_on_one_static_page()
    test_article_fixed_layout_uses_two_word_line_only_as_a_static_fallback()
    test_article_fixed_layout_keeps_numeric_magnitude_and_following_head_together()
    test_article_page_keeps_parser_supported_tight_nonfinite_complement_together()
    test_article_renderer_keeps_short_dangling_tail_on_one_static_page()
    test_article_renderer_keeps_a_complete_phrase_on_a_static_bilingual_page()
    test_chinese_visual_page_never_starts_with_attached_punctuation()
    test_article_renderer_keeps_modifier_head_phrase_on_one_visual_page()
    test_article_renderer_uses_pixel_width_for_43_character_chinese_cue()
    test_article_renderer_blocks_paginated_cue_without_verified_word_ledger()
    test_article_renderer_keeps_s0188_shape_as_static_two_line_page()
    test_article_renderer_rejects_word_ledger_text_mismatch()
    test_article_renderer_blocks_before_ffmpeg_for_unplanned_fixed_font_page()
    test_article_renderer_requires_verified_word_ledger_even_for_single_page_cues()
    test_standard_chinese_subtitle_font_uses_48_then_46_before_two_lines()
    test_article_template_scaled_geometry_stays_on_integer_pixels()
    test_article_template_tip_font_and_wrapper_support_chinese_text()
    test_article_concept_detail_wraps_after_a_semantic_lead_in()
    test_article_concept_detail_keeps_a_short_note_on_one_line()
    test_article_vocab_meaning_prefers_a_balanced_longer_second_line()
    test_article_vocab_meaning_keeps_lexical_units_and_edge_particles_attached()
    test_article_vocab_meaning_fails_instead_of_truncating_a_third_line()
    test_article_vocab_phrase_wraps_before_becoming_tiny()
    test_article_vocab_phrase_keeps_a_normal_short_phrase_on_one_line()
    test_article_vocab_phrase_only_uses_small_fallback_for_one_unbroken_word()
    test_article_vocab_phrase_fails_instead_of_shrinking_a_long_phrase_below_floor()
    test_article_vocab_typography_uses_bundled_role_specific_faces()
    test_article_vocab_detail_uses_roboto_slab_for_embedded_english()
    test_vocab_highlight_keeps_attached_punctuation_but_not_whitespace()
    test_standard_subtitle_highlight_colors_attached_punctuation()
    test_article_subtitle_highlight_colors_attached_punctuation()
    test_vocab_generation_fails_closed_after_preserving_successful_batches()
    test_empty_vocab_cache_is_regenerated_instead_of_reused()
    test_vocab_request_batches_balance_timeline_coverage()
    test_vocab_generation_resumes_only_unfinished_batches()
    test_successful_empty_vocab_batch_is_cached_as_complete()
    test_atomic_vocab_cache_write_preserves_previous_file_on_replace_failure()
    test_legacy_vocab_cache_cannot_authorize_an_incomplete_render()
    test_incomplete_vocab_cache_without_model_configuration_fails_closed()
    test_incomplete_vocab_plan_blocks_renderer_before_ffmpeg()
    test_article_template_requests_page_aligned_vocab_plan_before_ffmpeg()
    test_vocab_card_plan_keeps_the_latest_full_card_until_replacement()
    test_article_vocab_card_uses_only_expression_gloss_and_concept_note()
    test_vocab_prompt_requests_expression_card_fields_without_dictionary_metadata()
    test_vocab_plan_preserves_the_exact_phrase_from_its_subtitle()
    test_vocab_source_phrase_does_not_match_inside_a_larger_word()
    test_vocab_plan_limits_concept_cards_to_three_per_episode()
    test_vocab_plan_keeps_each_llm_card_inside_its_frozen_group()
    test_article_vocab_card_starts_on_the_final_page_that_contains_its_phrase()
    test_article_vocab_card_drops_a_phrase_split_across_final_pages()
    test_vocab_card_meaning_keeps_only_compact_primary_gloss()
    test_vocab_plan_normalizes_verbose_model_meaning_before_rendering()
    test_vocab_card_plan_skips_low_priority_model_candidates()
    test_vocab_card_plan_spreads_high_quality_candidates_across_the_episode()
    test_vocabulary_card_target_is_about_one_per_minute()
    test_article_template_does_not_fallback_to_per_subtitle_vocab_lookup()
    test_article_template_shows_topic_panel_before_first_card()
    test_article_template_first_vocab_card_is_full_strength_at_trigger_time()
    test_episode_vocab_overview_uses_editor_rank_instead_of_earliest_words()
    test_template_frame_cache_keeps_the_full_vocab_card_stable()
    test_stable_srt_writer_keeps_bilingual_original_top()
    test_id_bound_group_missing_one_id_does_not_shift_later_subtitles()
    test_atomic_no_response_cannot_be_written_as_affirmative()
    test_id_bound_group_rejects_duplicate_id_without_compressing_chinese()
    test_id_bound_group_rejects_unknown_id()
    test_id_bound_allocation_rejects_terminal_modifier_fragment()
    test_id_bound_allocation_accepts_terminal_shi_de_predicate()
    test_terminal_modifier_fragment_uses_specialized_fixed_id_retry()
    test_semantic_audit_does_not_flag_a_complete_single_cue_as_a_fragment()
    test_id_bound_group_allows_different_return_order()
    test_allocation_retry_preserves_initial_fixed_id_protocol_evidence()
    test_allocation_final_artifact_keeps_unresolved_group_fixed_id_mapping()
    test_single_cue_group_uses_authoritative_full_translation_without_allocation_request()
    test_single_cue_authoritative_translation_ending_in_de_is_not_an_allocation_fragment()
    test_just_because_non_entailment_translation_is_not_semantic_loss()
    test_invalid_single_cue_quality_preserves_authoritative_translation_for_review()
    test_missing_full_translation_does_not_discard_prior_fixed_id_allocation()
    test_full_translation_number_error_is_not_misclassified_as_allocation_error()
    test_full_translation_requests_are_chunked_and_retry_missing_groups()
    test_full_translation_missing_group_repair_has_a_hard_request_budget()
    test_full_translation_payload_includes_fixed_id_soft_reading_budgets()
    test_full_translation_prompt_restrains_ordinary_chinese_em_dashes()
    test_attached_backchannel_chinese_is_compacted_without_erasing_responses()
    test_full_translation_em_dash_style_detector_ignores_lexical_hyphen()
    test_full_translation_style_retry_only_retries_flagged_group_and_accepts_improvement()
    test_full_translation_style_retry_keeps_original_when_candidate_loses_number_or_negation()
    test_allocation_quality_retries_information_leaked_to_previous_id()
    test_allocation_quality_retries_displaced_main_clause_before_causal_id()
    test_allocation_quality_retries_orphaned_bare_preposition_prefix()
    test_allocation_quality_rejects_adjacent_core_duplication()
    test_allocation_quality_rejects_adjacent_long_common_phrase_duplication()
    test_allocation_quality_detects_negation_misplacement()
    test_allocation_quality_allows_negation_with_adjacent_predicate_completion()
    test_allocation_quality_accepts_common_chinese_negation_equivalents()
    test_allocation_quality_accepts_entity_spacing_equivalent()
    test_allocation_quality_accepts_chinese_number_equivalents()
    test_allocation_quality_accepts_decimal_wan_number_equivalent()
    test_number_anchor_accepts_billion_to_chinese_yi_conversion()
    test_number_anchor_accepts_decade_and_century_chinese_equivalents()
    test_negation_anchor_accepts_natural_chinese_question_tags_and_until_pattern()
    test_legacy_sample_specific_fragment_rules_are_not_hardcoded()
    test_allocation_quality_allows_adjacent_number_when_target_line_is_not_degraded()
    test_allocation_quality_rejects_adjacent_number_when_target_line_is_empty()
    test_allocation_quality_accepts_natural_subtitle_half_sentence()
    test_chinese_polish_rewrites_only_fixed_group_chinese_by_id()
    test_chinese_polish_skips_natural_groups_without_a_model_request()
    test_chinese_polish_selects_complex_comparison_group_by_fixed_ids()
    test_cross_subtitle_predicate_break_triggers_group_polish_by_fixed_ids()
    test_cross_subtitle_predicate_break_does_not_flag_normal_chinese_continuation()
    test_semantic_loss_recognizes_bingfei_as_negation()
    test_sentence_final_shide_is_not_a_dangling_chinese_fragment()
    test_allocation_retry_rejects_quality_regression_before_writeback()
    test_compare_allocation_candidates_accepts_strict_improvement_only()
    test_compare_allocation_candidates_rejects_new_high_confidence_issue()
    test_id_bound_candidate_decision_never_accepts_invalid_candidate()
    test_cross_id_leakage_requires_target_id_to_be_degraded()
    test_cross_id_leakage_flags_when_target_id_is_consumed_and_empty()
    test_cross_id_relation_marker_cannot_move_to_previous_question_id()
    test_allocation_quality_keeps_out_of_order_return_by_subtitle_id()
    test_allocation_concurrency_keeps_hit_only_context_for_cache_api_and_retry()
    test_allocation_quality_failed_group_does_not_shift_following_100_ids()
    test_compression_quality_regression_restores_previous_group_allocation()
    test_speed_compression_cannot_accept_number_omission_for_shorter_chinese()
    test_empty_middle_translation_keeps_its_own_id_slot()
    test_failed_group_does_not_shift_following_100_subtitles()
    test_failed_validation_does_not_write_final_output_file()
    test_invalid_final_timeline_blocks_before_display_page_translation()
    test_non_structural_validation_errors_do_not_block_render_gate()
    test_blocking_timeline_message_is_chinese_and_keeps_subtitle_position()
    test_final_segment_count_mismatch_is_structural_error()
    test_merge_preserves_ids_when_order_changes_before_final_write()
    test_repair_only_modifies_the_target_subtitle_id()
    test_compression_accepts_new_subtitle_id_protocol_without_position_shift()
    test_compression_rejects_legacy_index_only_response_without_writeback()
    test_group_reallocation_rejects_legacy_index_only_response()
    test_redistribution_parses_out_of_order_returns_by_subtitle_id()
    test_redistribution_parses_new_id_only_protocol_without_position_shift()
    test_compression_keeps_subtitle_ids_and_count()
    test_fallback_translation_fills_only_one_missing_subtitle_id()
    test_multiple_semantic_groups_apply_by_id_without_drift()
    test_full_merge_repair_chain_keeps_400_plus_ids_without_drift()
    test_passed_validation_writes_final_output_and_manifest_metadata()
    test_user_subtitle_exports_are_saved_to_media_result_folder()
    test_id_bound_mapping_has_no_drift_over_400_subtitles()
    test_runtime_module_import_path_is_available()
    test_whisperx_alignment_mapping_preserves_source_tokens_and_local_fallback()
    test_whisperx_expansion_compression_fallback_is_local_and_opt_in()
    test_whisperx_numeric_pause_collapse_restores_delayed_percentage_boundary()
    test_whisperx_numeric_pause_collapse_restores_prior_word_when_number_is_unmatched()
    test_whisperx_numeric_pause_guard_keeps_corroborated_local_shift()
    test_whisperx_plain_word_density_fallback_is_local()
    test_stable_ts_plain_word_density_fallback_keeps_valid_native_times()
    test_stable_ts_density_fallback_rejects_an_implausible_native_baseline()
    test_stable_ts_density_fallback_stops_on_an_unmappable_empty_token()
    test_whisperx_time_only_preserves_text_and_translation_while_retiming()
    test_whisperx_frozen_ledger_keeps_only_unmatched_word_on_stable_ts_time()
    test_whisperx_frozen_ledger_reverts_a_candidate_that_inverts_fallback_word_order()
    test_whisperx_frozen_ledger_keeps_monotonic_candidate_updates()
    test_whisperx_time_only_falls_back_to_stable_ledger_without_changing_cues()
    test_whisperx_time_only_uses_expanded_frozen_ledger_not_source_segment_count()
    test_whisperx_time_only_uses_explicit_source_audio_from_complete_task()
    test_screen_editor_normalizes_enum_target_language_for_prompts_and_artifacts()
    test_word_ledger_preserves_unicode_and_meaningful_connectors()
    test_short_nonindependent_backchannel_attaches_to_previous_display_item()
    test_short_backchannel_stays_with_following_coordinated_clause()
    test_pre_id_validation_keeps_terminal_backchannel_out_of_previous_sentence()
    test_complete_unsplittable_overflow_is_warning_not_overlong_error()
    test_context_rejected_overlong_split_is_structural_warning_not_error()
    test_stable_cut_keeps_an_unsplittable_complete_sentence_renderer_owned()
    test_overlong_repair_keeps_relative_clause_with_its_main_predicate()
    test_final_pre_id_repair_keeps_the_relative_clause_with_its_predicate()
    test_final_pre_id_repair_merges_subjectless_predicate_across_a_long_pause()
    test_stable_cut_does_not_leave_terminal_prepositional_phrase()
    test_comma_terminated_parser_confirmed_subordinate_overflow_is_warning_not_error()
    test_comma_overflow_requires_parser_proof_and_no_safe_split()
    test_adjacent_rebalance_preserves_sentence_boundary_before_complete_short_tail()
    test_visual_reading_budget_keeps_complete_13_word_cue_for_renderer_wrapping()
    test_visual_reading_budget_keeps_character_heavy_cue_for_renderer_wrapping()
    test_visual_reading_budget_never_selects_preposition_object_cut()
    test_visual_reading_budget_does_not_create_a_review_for_renderer_wrapping()
    test_visual_reading_budget_keeps_short_open_phrase_with_its_sentence()
    test_visual_reading_budget_keeps_a_single_clause_for_renderer_wrapping()
    test_visual_reading_budget_rejects_short_preposition_led_display_tail()
    test_visual_reading_budget_never_creates_parser_confirmed_example_preposition_cut()
    test_stable_cut_keeps_comma_bracketed_adverb_with_preceding_list_item()
    test_visual_budget_keeps_subject_with_delayed_finite_predicate()
    test_visual_budget_keeps_short_gerundial_manner_phrase_with_main_question()
    test_visual_temporal_budget_does_not_override_protected_fronted_introduction()
    test_visual_temporal_budget_splits_complete_punctuated_clauses()
    test_visual_temporal_budget_splits_complete_sentence_terminal()
    test_visual_temporal_budget_splits_complete_imperative_sentence_terminal()
    test_visual_temporal_budget_keeps_to_infinitive_with_its_main_clause()
    test_visual_temporal_budget_keeps_subject_with_delayed_predicate_despite_pause()
    test_visual_temporal_budget_rejects_punctuated_conditional_intro()
    test_final_timeline_rebuild_preserves_id_text_chinese_and_word_ownership()
    test_forced_alignment_finalization_never_moves_timing()
    test_duration_audit_reports_high_load_short_subtitle_as_warning()
    test_final_gate_blocks_protected_named_phrase_split()
    test_final_gate_blocks_protected_phrasal_boundary_split()
    test_final_gate_blocks_look_at_boundary_split()
    print("stable caption rule smoke tests passed")
