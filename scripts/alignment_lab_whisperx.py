import argparse
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


WORD_RE = re.compile(
    r"[A-Za-z]+(?:[-'’][A-Za-z]+)*(?:[.,!?;:]+)?"
    r"|\d+(?:[.,]\d+)*(?:%?)(?:[.,!?;:]+)?"
    r"|\S"
)


@dataclass
class Segment:
    text: str
    start_time: int
    end_time: int
    translated_text: str = ""


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_token(text: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)?", text or "")
    return parts[0].lower().replace("’", "'") if parts else (text or "").strip().lower()


def _tokenize(text: str) -> List[str]:
    return [token for token in WORD_RE.findall(text or "") if token.strip()]


def _load_segments_json(path: Path) -> List[Segment]:
    data = _read_json(path)
    if isinstance(data, dict) and "segments" in data and isinstance(data["segments"], list):
        items = data["segments"]
    elif isinstance(data, dict):
        items = [data[key] for key in sorted(data.keys(), key=lambda value: int(value))]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"Unsupported JSON shape: {path}")

    segments: List[Segment] = []
    for item in items:
        text = (
            item.get("text")
            or item.get("original_subtitle")
            or item.get("original")
            or item.get("word")
            or ""
        )
        if not str(text).strip():
            continue
        has_ms_keys = "start_time" in item or "end_time" in item
        start = item.get("start_time", item.get("start"))
        end = item.get("end_time", item.get("end"))
        if start is None or end is None:
            continue
        if has_ms_keys:
            start_ms = int(round(float(start)))
            end_ms = int(round(float(end)))
        else:
            start_ms = int(round(float(start) * 1000))
            end_ms = int(round(float(end) * 1000))
        if end_ms <= start_ms:
            end_ms = start_ms + 1
        segments.append(Segment(str(text), start_ms, end_ms))
    return sorted(segments, key=lambda seg: (seg.start_time, seg.end_time))


def _parse_srt_time(text: str) -> int:
    match = re.match(r"(\d{2}):(\d{2}):(\d{1,2})[,.](\d{3})", text.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {text}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3_600_000 + minutes * 60_000 + seconds * 1000 + millis


def _load_srt(path: Path) -> List[Segment]:
    text = path.read_text(encoding="utf-8-sig")
    segments: List[Segment] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        left, right = [part.strip() for part in lines[1].split("-->", 1)]
        start = _parse_srt_time(left)
        end = _parse_srt_time(right)
        original = lines[2].strip()
        translated = lines[3].strip() if len(lines) >= 4 else ""
        segments.append(Segment(original, start, end, translated))
    return segments


def _make_chunks(
    words: Sequence[Segment],
    max_chunk_ms: int,
) -> List[Dict]:
    if not words:
        return []
    chunks: List[Dict] = []
    start_index = 0
    while start_index < len(words):
        chunk_start = words[start_index].start_time
        end_index = start_index
        while end_index + 1 < len(words):
            candidate_end = words[end_index + 1].end_time
            if candidate_end - chunk_start > max_chunk_ms:
                break
            end_index += 1
        chunk_words = list(words[start_index : end_index + 1])
        chunks.append(
            {
                "chunk_index": len(chunks),
                "start_word_index": start_index,
                "end_word_index": end_index + 1,
                "start": chunk_start / 1000.0,
                "end": chunk_words[-1].end_time / 1000.0,
                "start_ms": chunk_start,
                "end_ms": chunk_words[-1].end_time,
                "word_count": len(chunk_words),
                "text": " ".join(seg.text.strip() for seg in chunk_words if seg.text.strip()),
            }
        )
        start_index = end_index + 1
    return chunks


def _find_ffmpeg() -> Optional[Path]:
    candidates = [
        ROOT / "resource" / "bin" / "ffmpeg.exe",
        ROOT / "resource" / "bin" / "Faster-Whisper-XXL" / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _ensure_ffmpeg_on_path() -> Optional[Path]:
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        os.environ["PATH"] = str(ffmpeg.parent) + os.pathsep + os.environ.get("PATH", "")
    return ffmpeg


def _srt_time(ms: int) -> str:
    ms = max(0, int(ms))
    total_seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _find_word_span(text: str, words: Sequence[Dict], cursor: int) -> Optional[Tuple[int, int]]:
    target = [_normalize_token(token) for token in _tokenize(text)]
    target = [token for token in target if token]
    if not target:
        return None
    max_start = max(cursor, len(words) - len(target))
    for start in range(cursor, max_start + 1):
        end = min(len(words), start + len(target))
        candidate = [_normalize_token(str(words[index].get("text") or "")) for index in range(start, end)]
        if candidate == target:
            return start, start + len(target)
    return None


def _percentile(values: Sequence[int], pct: float) -> Optional[int]:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(len(values) * pct)))
    return sorted(values)[index]


def _compare_word_ledgers(stable_words: Sequence[Segment], aligned_words: Sequence[Dict]) -> Dict:
    stable_norms = [_normalize_token(seg.text) for seg in stable_words]
    aligned_norms = [_normalize_token(str(item.get("text") or "")) for item in aligned_words]
    comparable = min(len(stable_norms), len(aligned_norms))
    matches = sum(1 for index in range(comparable) if stable_norms[index] == aligned_norms[index])
    monotonic_errors = 0
    previous_end = -1
    gaps: List[int] = []
    durations: List[int] = []
    for item in aligned_words:
        start = int(item["start_time"])
        end = int(item["end_time"])
        if start < previous_end:
            monotonic_errors += 1
        if previous_end >= 0:
            gaps.append(start - previous_end)
        durations.append(max(0, end - start))
        previous_end = max(previous_end, end)
    positive_gaps = [gap for gap in gaps if gap > 0]
    return {
        "stable_word_count": len(stable_words),
        "whisperx_word_count": len(aligned_words),
        "count_delta": len(aligned_words) - len(stable_words),
        "prefix_token_match_count": matches,
        "prefix_token_match_ratio": round(matches / comparable, 4) if comparable else 0.0,
        "monotonic_errors": monotonic_errors,
        "duration_ms": {
            "min": min(durations) if durations else None,
            "median": statistics.median(durations) if durations else None,
            "max": max(durations) if durations else None,
        },
        "positive_gap_ms": {
            "count": len(positive_gaps),
            "median": statistics.median(positive_gaps) if positive_gaps else 0,
            "p90": _percentile(positive_gaps, 0.9) or 0,
            "max": max(positive_gaps) if positive_gaps else 0,
            "gt300": sum(gap > 300 for gap in positive_gaps),
            "gt500": sum(gap > 500 for gap in positive_gaps),
            "gt800": sum(gap > 800 for gap in positive_gaps),
        },
    }


def _write_preview_srt(
    stable_srt_path: Path,
    aligned_words: Sequence[Dict],
    output_path: Path,
) -> Dict:
    stable_segments = _load_srt(stable_srt_path)
    cursor = 0
    aligned = 0
    fallback = 0
    blocks: List[str] = []
    mapping: List[Dict] = []
    for index, seg in enumerate(stable_segments, 1):
        match = _find_word_span(seg.text, aligned_words, cursor)
        if match:
            start_index, end_index = match
            start_time = int(aligned_words[start_index]["start_time"])
            end_time = int(aligned_words[end_index - 1]["end_time"])
            cursor = end_index
            aligned += 1
            source = "whisperx"
        else:
            start_time = seg.start_time
            end_time = seg.end_time
            fallback += 1
            start_index = None
            end_index = None
            source = "stable_fallback"
        body = [seg.text]
        if seg.translated_text:
            body.append(seg.translated_text)
        mapping.append(
            {
                "subtitle_index": index,
                "source": source,
                "word_range": [start_index, end_index] if match else None,
                "stable_start_time": seg.start_time,
                "stable_end_time": seg.end_time,
                "preview_start_time": start_time,
                "preview_end_time": max(end_time, start_time + 1),
                "english": seg.text,
            }
        )
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_srt_time(start_time)} --> {_srt_time(max(end_time, start_time + 1))}",
                    *body,
                ]
            )
        )
    output_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    _write_json(output_path.with_name("whisperx-preview-mapping.json"), mapping)
    return {"preview_segments": len(stable_segments), "aligned": aligned, "fallback": fallback}


def _extract_aligned_words(result: Dict) -> List[Dict]:
    words: List[Dict] = []
    for segment in result.get("segments", []) or []:
        for word in segment.get("words", []) or []:
            text = str(word.get("word") or word.get("text") or "").strip()
            if not text or "start" not in word or "end" not in word:
                continue
            start_ms = int(round(float(word["start"]) * 1000))
            end_ms = int(round(float(word["end"]) * 1000))
            if end_ms <= start_ms:
                end_ms = start_ms + 1
            words.append(
                {
                    "index": len(words),
                    "text": text,
                    "start_time": start_ms,
                    "end_time": end_ms,
                    "score": word.get("score"),
                    "segment_start": segment.get("start"),
                    "segment_end": segment.get("end"),
                }
            )
    return words


def run_whisperx_alignment(
    audio_path: Path,
    stable_words: Sequence[Segment],
    output_dir: Path,
    language: str,
    device: str,
    align_model: Optional[str],
    max_chunk_ms: int,
    interpolate_method: str,
    dry_run: bool = False,
) -> Tuple[List[Dict], Dict]:
    chunks = _make_chunks(stable_words, max_chunk_ms=max_chunk_ms)
    manifest = {
        "audio_path": str(audio_path),
        "stable_word_count": len(stable_words),
        "chunk_count": len(chunks),
        "max_chunk_ms": max_chunk_ms,
        "language": language,
        "device": device,
        "align_model": align_model,
        "interpolate_method": interpolate_method,
        "dry_run": dry_run,
        "chunks": chunks,
    }
    _write_json(output_dir / "whisperx-alignment-inputs.json", manifest)
    if dry_run:
        return [], manifest

    started_at = time.perf_counter()
    try:
        import whisperx
    except ImportError as exc:
        raise RuntimeError("whisperx is not installed in this Python environment") from exc

    ffmpeg = _ensure_ffmpeg_on_path()
    audio = whisperx.load_audio(str(audio_path))
    model_a, metadata = whisperx.load_align_model(
        language_code=language,
        device=device,
        model_name=align_model,
    )
    result = whisperx.align(
        chunks,
        model_a,
        metadata,
        audio,
        device,
        interpolate_method=interpolate_method,
        return_char_alignments=False,
    )
    aligned_words = _extract_aligned_words(result)
    manifest["elapsed_seconds"] = round(time.perf_counter() - started_at, 3)
    manifest["ffmpeg"] = str(ffmpeg) if ffmpeg else None
    _write_json(output_dir / "whisperx-alignment-raw-return.json", result)
    return aligned_words, manifest


def check_environment() -> Dict:
    import importlib.util

    result = {
        "python": sys.executable,
        "whisperx": importlib.util.find_spec("whisperx") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
        "torchaudio": importlib.util.find_spec("torchaudio") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "ffmpeg": str(_find_ffmpeg()) if _find_ffmpeg() else None,
    }
    if result["torch"]:
        import torch

        result["cuda_available"] = bool(torch.cuda.is_available())
        result["cuda_device_count"] = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
        result["torch_version"] = torch.__version__
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WhisperX forced-alignment lab for frozen FasterWhisper transcripts.")
    parser.add_argument("--audio", type=Path, help="Audio file path.")
    parser.add_argument("--stable-word-json", type=Path, help="Existing stable-ts/asr_corrected word JSON.")
    parser.add_argument("--stable-preview-srt", type=Path, help="Stable final SRT used to build whisperx-aligned preview SRT.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--align-model", default=None)
    parser.add_argument("--max-chunk-ms", type=int, default=30_000)
    parser.add_argument("--interpolate-method", default="nearest", choices=["nearest", "linear", "ignore"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-env", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    env = check_environment()
    _write_json(args.output_dir / "whisperx-alignment-env.json", env)
    if args.check_env:
        print(json.dumps(env, ensure_ascii=False, indent=2))
        return 0

    if not args.audio or not args.stable_word_json:
        raise SystemExit("--audio and --stable-word-json are required unless --check-env is used")

    stable_words = _load_segments_json(args.stable_word_json)
    aligned_words, manifest = run_whisperx_alignment(
        audio_path=args.audio,
        stable_words=stable_words,
        output_dir=args.output_dir,
        language=args.language,
        device=args.device,
        align_model=args.align_model,
        max_chunk_ms=args.max_chunk_ms,
        interpolate_method=args.interpolate_method,
        dry_run=args.dry_run,
    )
    _write_json(args.output_dir / "whisperx-alignment-manifest.json", manifest)

    if args.dry_run:
        print(json.dumps({"status": "dry_run", "chunk_count": manifest["chunk_count"]}, ensure_ascii=False, indent=2))
        return 0

    _write_json(args.output_dir / "whisperx-word-ledger.json", aligned_words)
    report = _compare_word_ledgers(stable_words, aligned_words)
    if args.stable_preview_srt:
        preview_path = args.output_dir / "whisperx-aligned-preview.srt"
        report["preview_srt"] = str(preview_path)
        report["preview"] = _write_preview_srt(args.stable_preview_srt, aligned_words, preview_path)
    _write_json(args.output_dir / "alignment-compare-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
