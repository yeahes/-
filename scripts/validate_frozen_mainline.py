import argparse
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.subtitle_processor.final_cue_timeline import (
    derive_final_cue_timeline,
    reconcile_frozen_word_ledger,
)
from app.core.subtitle_processor.screen_editor import (
    DISPLAY_LEAD_IN_MS,
    DISPLAY_TAIL_PADDING_MS,
    ScreenSubtitleEditor,
    ScreenSubtitleItem,
)
from app.core.subtitle_processor.stable_ts_alignment import (
    align_frozen_word_ledger_with_whisperx,
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(payload) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ordered_values(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload[key] for key in sorted(payload, key=lambda value: int(value) if str(value).isdigit() else str(value))]
    return []


def _load_asr(path: Path) -> ASRData:
    segments = []
    for item in _ordered_values(_read_json(path)):
        text = str(item.get("original_subtitle") or item.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            ASRDataSeg(
                text=text,
                start_time=int(item.get("start_time", item.get("start_ms", 0)) or 0),
                end_time=int(item.get("end_time", item.get("end_ms", 0)) or 0),
                translated_text=str(item.get("translated_subtitle") or item.get("translated_text") or ""),
            )
        )
    return ASRData(segments)


def _load_items(spans: list[dict]) -> list[ScreenSubtitleItem]:
    return [
        ScreenSubtitleItem(
            source_ids=list(item.get("source_ids") or []),
            original=str(item.get("original") or ""),
            translated=str(item.get("translated") or ""),
            word_start=item.get("word_start"),
            word_end=item.get("word_end"),
            subtitle_id=str(item.get("subtitle_id") or ""),
        )
        for item in spans
    ]


def _item_payload(items: list[ScreenSubtitleItem]) -> list[dict]:
    return [
        {
            "subtitle_id": str(item.subtitle_id or ""),
            "word_start": item.word_start,
            "word_end": item.word_end,
            "english": item.original,
        }
        for item in items
    ]


def _boundary_ranges(items: list[ScreenSubtitleItem]) -> set[tuple[int, int]]:
    result = set()
    for left, right in zip(items, items[1:]):
        if left.word_end is None or right.word_start is None:
            continue
        result.add((int(left.word_end), int(right.word_start)))
    return result


def _hard_boundary_issues(editor: ScreenSubtitleEditor, items: list[ScreenSubtitleItem]) -> list[dict]:
    issues = []
    for left, right in zip(items, items[1:]):
        if left.word_end is None or right.word_start is None:
            continue
        if int(right.word_start) != int(left.word_end) + 1:
            continue
        evaluation = editor._evaluate_stable_cut_boundary(
            int(left.word_end),
            int(right.word_start),
            source_start=max(0, int(left.word_start or 0) - 8),
            source_end=min(len(editor._active_word_entries) - 1, int(right.word_end or 0) + 8),
        )
        if evaluation["hard_issues"]:
            issues.append(
                {
                    "left_subtitle_id": str(left.subtitle_id or ""),
                    "right_subtitle_id": str(right.subtitle_id or ""),
                    "left_english": left.original,
                    "right_english": right.original,
                    "word_boundary": [int(left.word_end), int(right.word_start)],
                    "hard_issues": evaluation["hard_issues"],
                    "pause_ms": evaluation["pause_ms"],
                }
            )
    return issues


def _prepare_cut_editor(word_data: ASRData, source_data: ASRData, max_words: int) -> ScreenSubtitleEditor:
    # The replay only invokes deterministic, local segmentation methods.  The
    # production constructor otherwise requires LLM credentials even though no
    # LLM request is possible on this path.
    original_init_client = ScreenSubtitleEditor._init_client
    ScreenSubtitleEditor._init_client = staticmethod(lambda: None)
    try:
        editor = ScreenSubtitleEditor(
            model="frozen-validation-no-llm",
            max_cjk_chars=28,
            max_english_words=max_words,
            enable_stable_mode=True,
            enable_quality_check=False,
        )
    finally:
        ScreenSubtitleEditor._init_client = original_init_client
    editor._active_word_entries = editor._word_time_entries(word_data.segments)
    editor._active_source_word_spans = editor._map_source_segments_to_word_entries(
        source_data.segments, editor._active_word_entries
    )
    editor._active_source_segments_by_id = {
        index: segment for index, segment in enumerate(source_data.segments, 1)
    }
    editor._prepare_syntax_cut_hints()
    return editor


def _replay_cut(editor: ScreenSubtitleEditor, source_data: ASRData) -> list[ScreenSubtitleItem]:
    # Reuse the sole production owner of stable English boundaries.  Keeping a
    # hand-copied list here previously preserved a retired article-layout
    # recut, making the diagnostic report claim a boundary drift that the
    # production pipeline could no longer create.
    items = editor._finalize_stable_english_boundaries(source_data.segments)
    return editor._assign_global_subtitle_ids(items)


def _word_coverage(items: list[ScreenSubtitleItem], word_count: int) -> dict:
    ranges = [(item.word_start, item.word_end) for item in items]
    contiguous = bool(ranges)
    previous_end = -1
    for start, end in ranges:
        if start is None or end is None or int(start) != previous_end + 1 or int(end) < int(start):
            contiguous = False
            break
        previous_end = int(end)
    return {
        "contiguous": contiguous,
        "first_word": ranges[0][0] if ranges else None,
        "last_word": ranges[-1][1] if ranges else None,
        "word_count": word_count,
        "complete": contiguous and bool(ranges) and int(ranges[0][0]) == 0 and int(ranges[-1][1]) == word_count - 1,
    }


def _timing_metrics(segments: list[ASRDataSeg]) -> dict:
    durations = [max(0, int(item.end_time) - int(item.start_time)) for item in segments]
    gaps = [
        int(right.start_time) - int(left.end_time)
        for left, right in zip(segments, segments[1:])
    ]
    return {
        "cue_count": len(segments),
        "duration_ms": {
            "minimum": min(durations) if durations else None,
            "median": statistics.median(durations) if durations else None,
            "under_250": sum(value < 250 for value in durations),
            "under_500": sum(value < 500 for value in durations),
            "under_700": sum(value < 700 for value in durations),
        },
        "gaps": {
            "overlap_count": sum(value < 0 for value in gaps),
            "gt800": sum(value > 800 for value in gaps),
            "gt1000": sum(value > 1000 for value in gaps),
            "max": max(gaps) if gaps else 0,
        },
    }


def _sorted_subtitle_ids(records: list[dict]) -> list[str]:
    ids = [str(record.get("subtitle_id") or "") for record in records]
    if any(not re.fullmatch(r"S\d{4}", subtitle_id) or subtitle_id == "S0000" for subtitle_id in ids):
        raise ValueError("subtitle-spans contains a missing or synthetic subtitle_id")
    if len(ids) != len(set(ids)):
        raise ValueError("subtitle-spans contains duplicate subtitle_id values")
    return sorted(ids, key=lambda subtitle_id: int(subtitle_id[1:]))


def _ledger_asr_data(ledger: dict) -> ASRData:
    segments: list[ASRDataSeg] = []
    for word in ledger.get("words") or []:
        segment = ASRDataSeg(
            text=str(word.get("surface") or ""),
            start_time=int(word.get("start_ms") or 0),
            end_time=int(word.get("end_ms") or 0),
        )
        segment.word_id = int(word.get("word_id"))
        segment.alignment_source = str(word.get("alignment_source") or "stable-ts")
        segments.append(segment)
    return ASRData(segments)


def _final_segments_by_id(artifact_dir: Path, spans: list[dict]) -> dict[str, ASRDataSeg]:
    translations_path = artifact_dir / "translations.json"
    translations = _ordered_values(_read_json(translations_path))
    translation_by_id: dict[str, dict] = {}
    for record in translations:
        subtitle_id = str(record.get("subtitle_id") or "")
        if not re.fullmatch(r"S\d{4}", subtitle_id) or subtitle_id == "S0000":
            raise ValueError(f"translations contains invalid subtitle_id: {subtitle_id!r}")
        if subtitle_id in translation_by_id:
            raise ValueError(f"translations contains duplicate subtitle_id: {subtitle_id}")
        translation_by_id[subtitle_id] = record

    expected_ids = _sorted_subtitle_ids(spans)
    if set(translation_by_id) != set(expected_ids):
        raise ValueError("translations subtitle_id set does not match frozen subtitle-spans")

    span_by_id = {str(span["subtitle_id"]): span for span in spans}
    result: dict[str, ASRDataSeg] = {}
    for subtitle_id in expected_ids:
        span = span_by_id[subtitle_id]
        translation = translation_by_id[subtitle_id]
        if str(translation.get("text") or "") != str(span.get("original") or ""):
            raise ValueError(f"final English text differs from frozen span: {subtitle_id}")
        segment = ASRDataSeg(
            text=str(translation.get("text") or ""),
            translated_text=str(translation.get("translated_text") or ""),
            start_time=int(translation.get("start_ms") or 0),
            end_time=int(translation.get("end_ms") or 0),
        )
        segment.subtitle_id = subtitle_id
        segment.word_start = int(span.get("word_start"))
        segment.word_end = int(span.get("word_end"))
        result[subtitle_id] = segment
    return result


def _time_only_replay(
    audio: Path,
    alignment_source: ASRData,
    spans: list[dict],
    ledger: dict,
    artifact_dir: Path,
    output_dir: Path,
) -> dict:
    expected_ids = _sorted_subtitle_ids(spans)
    before_by_id = _final_segments_by_id(artifact_dir, spans)
    original = ASRData([before_by_id[subtitle_id] for subtitle_id in expected_ids])
    aligned_ledger = align_frozen_word_ledger_with_whisperx(
        str(audio),
        alignment_source,
        _ledger_asr_data(ledger),
        language="en",
    )
    if aligned_ledger is None:
        return {"status": "failed", "reason": "whisperx_frozen_word_alignment_returned_none"}

    reconciliation = reconcile_frozen_word_ledger(
        [
            {
                "word_id": int(getattr(word, "word_id", index)),
                "surface": word.text,
                "start_ms": int(word.start_time),
                "end_ms": int(word.end_time),
                "alignment_source": str(getattr(word, "alignment_source", "stable-ts")),
            }
            for index, word in enumerate(aligned_ledger.segments)
        ]
    )
    if reconciliation.get("errors"):
        return {"status": "failed", "reason": "frozen_word_reconciliation_failed", "errors": reconciliation["errors"]}

    span_by_id = {str(span["subtitle_id"]): span for span in spans}
    timeline = derive_final_cue_timeline(
        [
            {
                "subtitle_id": subtitle_id,
                "word_start": int(span_by_id[subtitle_id]["word_start"]),
                "word_end": int(span_by_id[subtitle_id]["word_end"]),
            }
            for subtitle_id in expected_ids
        ],
        reconciliation["words"],
        expected_subtitle_ids=expected_ids,
        lead_in_ms=DISPLAY_LEAD_IN_MS,
        tail_padding_ms=DISPLAY_TAIL_PADDING_MS,
    )
    records_by_id = {str(record["subtitle_id"]): record for record in timeline.get("records") or []}
    if timeline.get("validation", {}).get("status") != "PASS":
        return {"status": "failed", "reason": "final_cue_timeline_invalid", "timeline": timeline}
    if set(records_by_id) != set(expected_ids):
        return {"status": "failed", "reason": "final_cue_timeline_id_set_mismatch", "timeline": timeline}

    timeline_output = output_dir / "final-cue-timeline.json"
    _write_json(timeline_output, timeline)

    rebuilt_segments: list[ASRDataSeg] = []
    for subtitle_id in expected_ids:
        before = before_by_id[subtitle_id]
        record = records_by_id[subtitle_id]
        rebuilt = ASRDataSeg(
            text=before.text,
            translated_text=before.translated_text,
            start_time=int(record["start_ms"]),
            end_time=int(record["end_ms"]),
        )
        rebuilt.subtitle_id = subtitle_id
        rebuilt.word_start = int(record["word_start"])
        rebuilt.word_end = int(record["word_end"])
        rebuilt_segments.append(rebuilt)

    remapped = ASRData(rebuilt_segments)
    before_payload = {
        subtitle_id: (segment.text, segment.translated_text, segment.start_time, segment.end_time)
        for subtitle_id, segment in before_by_id.items()
    }
    after_payload = {
        str(segment.subtitle_id): (segment.text, segment.translated_text, segment.start_time, segment.end_time)
        for segment in remapped.segments
    }
    text_changed = [
        subtitle_id
        for subtitle_id in expected_ids
        if before_payload[subtitle_id][:2] != after_payload[subtitle_id][:2]
    ]
    start_deltas = [
        after_payload[subtitle_id][2] - before_payload[subtitle_id][2]
        for subtitle_id in expected_ids
    ]
    end_deltas = [
        after_payload[subtitle_id][3] - before_payload[subtitle_id][3]
        for subtitle_id in expected_ids
    ]
    changed = sum(
        before_payload[subtitle_id][2:] != after_payload[subtitle_id][2:]
        for subtitle_id in expected_ids
    )
    output = output_dir / "whisperx-time-only.srt"
    remapped.to_srt(save_path=str(output), layout="原文在上")
    return {
        "status": "passed" if not text_changed and len(remapped.segments) == len(original.segments) else "failed",
        "text_changed_subtitle_ids": text_changed,
        "timing_changed_count": changed,
        "matched_word_count": int(getattr(aligned_ledger, "whisperx_matched_word_count", 0)),
        "frozen_word_fallback_count": int(getattr(aligned_ledger, "whisperx_fallback_word_count", 0)),
        "word_boundary_reconciliation_count": len(reconciliation.get("reconciliations") or []),
        "final_timeline_validation": timeline.get("validation") or {},
        "final_timeline_output": str(timeline_output),
        "before": _timing_metrics(original.segments),
        "after": _timing_metrics(remapped.segments),
        "start_delta_ms": {
            "median": statistics.median(start_deltas) if start_deltas else 0,
            "minimum": min(start_deltas) if start_deltas else 0,
            "maximum": max(start_deltas) if start_deltas else 0,
        },
        "end_delta_ms": {
            "median": statistics.median(end_deltas) if end_deltas else 0,
            "minimum": min(end_deltas) if end_deltas else 0,
            "maximum": max(end_deltas) if end_deltas else 0,
        },
        "output_srt": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay frozen stable cutting and optional WhisperX frozen-word alignment."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--asr-corrected", required=True, type=Path)
    parser.add_argument("--stable-srt", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--max-english-words", type=int, default=16)
    parser.add_argument("--run-whisperx", action="store_true")
    args = parser.parse_args()

    artifact_dir = args.artifact_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    spans = _read_json(artifact_dir / "subtitle-spans.json")
    ledger = _read_json(artifact_dir / "word-ledger.json")
    source_data = _load_asr(args.asr_corrected)
    word_data = _load_asr(args.asr_corrected)
    baseline_items = _load_items(spans)
    editor = _prepare_cut_editor(word_data, source_data, args.max_english_words)
    replay_items = _replay_cut(editor, source_data)
    baseline_issues = _hard_boundary_issues(editor, baseline_items)
    replay_issues = _hard_boundary_issues(editor, replay_items)
    baseline_boundaries = _boundary_ranges(baseline_items)
    replay_boundaries = _boundary_ranges(replay_items)
    report = {
        "sample": args.name,
        "artifact_dir": str(artifact_dir),
        "asr_corrected": str(args.asr_corrected.resolve()),
        "stable_srt": str(args.stable_srt.resolve()),
        "frozen_input_hashes": {
            "asr_corrected": _sha256(_read_json(args.asr_corrected)),
            "word_ledger": _sha256(ledger),
            "baseline_spans": _sha256(spans),
        },
        "english_cut": {
            "baseline_subtitle_count": len(baseline_items),
            "replay_subtitle_count": len(replay_items),
            "baseline_payload_hash": _sha256(_item_payload(baseline_items)),
            "replay_payload_hash": _sha256(_item_payload(replay_items)),
            "baseline_coverage": _word_coverage(baseline_items, len(ledger.get("words") or [])),
            "replay_coverage": _word_coverage(replay_items, len(ledger.get("words") or [])),
            "baseline_hard_issue_count": len(baseline_issues),
            "replay_hard_issue_count": len(replay_issues),
            "baseline_hard_issues": baseline_issues,
            "replay_hard_issues": replay_issues,
            "added_boundaries": [list(value) for value in sorted(replay_boundaries - baseline_boundaries)],
            "removed_boundaries": [list(value) for value in sorted(baseline_boundaries - replay_boundaries)],
            "subtitle_ids_sequential": [item.subtitle_id for item in replay_items] == [f"S{index:04d}" for index in range(1, len(replay_items) + 1)],
        },
    }
    if args.run_whisperx:
        if not args.audio or not args.audio.exists():
            raise ValueError("--audio must reference the original audio when --run-whisperx is enabled")
        report["whisperx_time_only"] = _time_only_replay(
            args.audio.resolve(), source_data, spans, ledger, artifact_dir, output_dir
        )
    _write_json(output_dir / "frozen-mainline-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
