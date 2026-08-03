import argparse
import json
from pathlib import Path

from app.core.bk_asr.asr_data import ASRDataSeg
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ordered_values(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload[key] for key in sorted(payload, key=lambda value: int(value) if str(value).isdigit() else str(value))]
    return []


def _source_segments(path: Path):
    return [
        ASRDataSeg(
            text=str(item.get("original_subtitle") or item.get("text") or ""),
            start_time=int(item.get("start_time", item.get("start_ms", 0)) or 0),
            end_time=int(item.get("end_time", item.get("end_ms", 0)) or 0),
        )
        for item in _ordered_values(_read_json(path))
        if str(item.get("original_subtitle") or item.get("text") or "").strip()
    ]


def _final_segments(artifact_dir: Path):
    spans = {str(item.get("subtitle_id") or ""): item for item in _read_json(artifact_dir / "subtitle-spans.json")}
    words = list((_read_json(artifact_dir / "word-ledger.json").get("words") or []))
    segments = []
    for item in _read_json(artifact_dir / "translations.json"):
        subtitle_id = str(item.get("subtitle_id") or "")
        span = spans.get(subtitle_id) or {}
        segment = ASRDataSeg(
            text=str(item.get("text") or ""),
            translated_text=str(item.get("translated_text") or ""),
            start_time=int(item.get("start_ms", 0) or 0),
            end_time=int(item.get("end_ms", 0) or 0),
        )
        segment.subtitle_id = subtitle_id
        segment.word_start = span.get("word_start")
        segment.word_end = span.get("word_end")
        if isinstance(segment.word_start, int) and isinstance(segment.word_end, int) and 0 <= segment.word_start <= segment.word_end < len(words):
            segment.stable_word_start_ms = int(words[segment.word_start].get("start_ms", 0) or 0)
            segment.stable_word_end_ms = int(words[segment.word_end].get("end_ms", 0) or 0)
        segments.append(segment)
    return segments


def _srt_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours = milliseconds // 3_600_000
    minutes = (milliseconds % 3_600_000) // 60_000
    seconds = (milliseconds % 60_000) // 1_000
    remainder = milliseconds % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{remainder:03d}"


def _write_bilingual_original_top_srt(segments, output: Path) -> None:
    lines = []
    for index, segment in enumerate(segments, 1):
        lines.extend(
            [
                str(index),
                f"{_srt_timestamp(segment.start_time)} --> {_srt_timestamp(segment.end_time)}",
                (segment.text or "").strip(),
                (segment.translated_text or "").strip(),
                "",
            ]
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8-sig")


def main():
    parser = argparse.ArgumentParser(description="Replay final subtitle display coverage repair without LLM calls.")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--asr-corrected", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--output-srt",
        help="Optional bilingual original-on-top SRT written from the replayed final timings.",
    )
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    source = _source_segments(Path(args.asr_corrected))
    before = _final_segments(artifact_dir)
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor._display_coverage_repairs = []
    editor._display_coverage_unresolved = []
    after = editor._reconcile_final_display_coverage(before, source)
    changed = [
        {
            "subtitle_id": str(new.subtitle_id),
            "before": [int(old.start_time), int(old.end_time)],
            "after": [int(new.start_time), int(new.end_time)],
        }
        for old, new in zip(before, after)
        if (int(old.start_time), int(old.end_time)) != (int(new.start_time), int(new.end_time))
    ]
    immutable = all(
        (old.text, old.translated_text, getattr(old, "subtitle_id", ""), getattr(old, "word_start", None), getattr(old, "word_end", None))
        == (new.text, new.translated_text, getattr(new, "subtitle_id", ""), getattr(new, "word_start", None), getattr(new, "word_end", None))
        for old, new in zip(before, after)
    )
    report = {
        "artifact_dir": str(artifact_dir),
        "asr_corrected": str(args.asr_corrected),
        "subtitle_count": len(before),
        "source_word_count": len(source),
        "timing_changed_count": len(changed),
        "immutable_subtitle_fields_preserved": immutable,
        "timing_changes": changed,
        "repairs": editor._display_coverage_repairs,
        "unresolved": editor._display_coverage_unresolved,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_srt:
        _write_bilingual_original_top_srt(after, Path(args.output_srt))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
