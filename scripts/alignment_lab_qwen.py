import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg


WORD_RE = re.compile(
    r"[A-Za-z]+(?:[-'’][A-Za-z]+)*(?:[.,!?;:]+)?"
    r"|\d+(?:[.,]\d+)*(?:%?)(?:[.,!?;:]+)?"
    r"|\S"
)


LANGUAGE_MAP = {
    "en": "English",
    "english": "English",
    "zh": "Chinese",
    "chinese": "Chinese",
}


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


def _load_segments_json(path: Path) -> List[ASRDataSeg]:
    data = _read_json(path)
    if isinstance(data, dict) and "segments" in data and isinstance(data["segments"], list):
        items = data["segments"]
    elif isinstance(data, dict):
        items = [data[key] for key in sorted(data.keys(), key=lambda value: int(value))]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"Unsupported JSON shape: {path}")

    segments: List[ASRDataSeg] = []
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
        segments.append(ASRDataSeg(str(text), start_ms, end_ms))
    return sorted(segments, key=lambda seg: (seg.start_time, seg.end_time))


def _load_srt(path: Path) -> List[ASRDataSeg]:
    return ASRData.from_srt(path.read_text(encoding="utf-8-sig")).segments


def _load_audio_slice(audio_path: Path, start_ms: int, end_ms: int):
    offset = max(0.0, start_ms / 1000.0)
    duration = max(0.01, (end_ms - start_ms) / 1000.0)
    try:
        import librosa

        waveform, sample_rate = librosa.load(
            str(audio_path),
            sr=16000,
            mono=True,
            offset=offset,
            duration=duration,
        )
        return waveform, sample_rate
    except Exception:
        pass

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("No audio slice backend available: install librosa or provide ffmpeg.exe")

    import numpy as np

    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{offset:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-2000:])
    return np.frombuffer(result.stdout, dtype=np.float32), 16000


def _find_ffmpeg() -> Optional[Path]:
    candidates = [
        ROOT / "resource" / "bin" / "ffmpeg.exe",
        ROOT / "resource" / "bin" / "Faster-Whisper-XXL" / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _make_chunks(
    words: Sequence[ASRDataSeg],
    max_chunk_ms: int,
    pad_ms: int,
) -> List[Dict]:
    if not words:
        return []
    chunks: List[Dict] = []
    start_index = 0
    while start_index < len(words):
        chunk_start = max(0, words[start_index].start_time - pad_ms)
        end_index = start_index
        while end_index + 1 < len(words):
            candidate_end = words[end_index + 1].end_time + pad_ms
            if candidate_end - chunk_start > max_chunk_ms:
                break
            end_index += 1
        chunk_words = list(words[start_index : end_index + 1])
        chunks.append(
            {
                "chunk_index": len(chunks),
                "start_word_index": start_index,
                "end_word_index": end_index + 1,
                "audio_start_ms": chunk_start,
                "audio_end_ms": chunk_words[-1].end_time + pad_ms,
                "word_count": len(chunk_words),
                "text": " ".join(seg.text.strip() for seg in chunk_words if seg.text.strip()),
            }
        )
        start_index = end_index + 1
    return chunks


def _torch_dtype(dtype_name: str, device: str):
    import torch

    dtype_name = (dtype_name or "").lower()
    if device == "cpu":
        return torch.float32
    if dtype_name in {"bfloat16", "bf16"}:
        return torch.bfloat16
    if dtype_name in {"float32", "fp32"}:
        return torch.float32
    return torch.float16


def _load_qwen_aligner(model_name: str, device: str, dtype_name: str):
    import torch
    try:
        from qwen_asr import Qwen3ForcedAligner
    except ImportError as exc:
        raise RuntimeError(
            "qwen_asr is not installed. Install it in a separate lab environment "
            "with: python -m pip install qwen-asr transformers accelerate"
        ) from exc

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    kwargs = {
        "dtype": _torch_dtype(dtype_name, device),
        "device_map": "cuda:0" if device == "cuda" else "cpu",
    }
    if device == "cuda":
        kwargs["low_cpu_mem_usage"] = True
    return Qwen3ForcedAligner.from_pretrained(model_name, **kwargs), device


def _extract_qwen_words(result) -> List[Dict]:
    # Qwen returns list-like timestamp units. Each unit exposes text/start_time/end_time.
    units = result[0] if result and isinstance(result, list) and result and isinstance(result[0], list) else result
    words: List[Dict] = []
    for item in units or []:
        text = str(getattr(item, "text", "")).strip()
        if not text:
            continue
        start = float(getattr(item, "start_time", 0.0))
        end = float(getattr(item, "end_time", start))
        words.append({"text": text, "start": start, "end": max(end, start)})
    return words


def run_qwen_alignment(
    audio_path: Path,
    stable_words: Sequence[ASRDataSeg],
    output_dir: Path,
    language: str,
    model_name: str,
    device: str,
    dtype_name: str,
    max_chunk_ms: int,
    pad_ms: int,
    dry_run: bool = False,
) -> Tuple[List[Dict], Dict]:
    chunks = _make_chunks(stable_words, max_chunk_ms=max_chunk_ms, pad_ms=pad_ms)
    manifest = {
        "audio_path": str(audio_path),
        "stable_word_count": len(stable_words),
        "chunk_count": len(chunks),
        "max_chunk_ms": max_chunk_ms,
        "pad_ms": pad_ms,
        "language": language,
        "model_name": model_name,
        "dry_run": dry_run,
        "chunks": chunks,
    }
    _write_json(output_dir / "qwen-alignment-inputs.json", manifest)
    if dry_run:
        return [], manifest

    started_at = time.perf_counter()
    aligner, resolved_device = _load_qwen_aligner(model_name, device, dtype_name)
    language_name = LANGUAGE_MAP.get(language.lower(), language)
    aligned_words: List[Dict] = []
    raw_returns: List[Dict] = []

    for chunk in chunks:
        waveform, sample_rate = _load_audio_slice(
            audio_path,
            int(chunk["audio_start_ms"]),
            int(chunk["audio_end_ms"]),
        )
        result = aligner.align(
            audio=(waveform, sample_rate),
            text=chunk["text"],
            language=language_name,
        )
        chunk_words = _extract_qwen_words(result)
        raw_returns.append(
            {
                "chunk_index": chunk["chunk_index"],
                "word_count": len(chunk_words),
                "raw_words": chunk_words,
            }
        )
        offset_ms = int(chunk["audio_start_ms"])
        for word in chunk_words:
            start_ms = offset_ms + int(round(float(word["start"]) * 1000))
            end_ms = offset_ms + int(round(float(word["end"]) * 1000))
            if end_ms <= start_ms:
                end_ms = start_ms + 1
            aligned_words.append(
                {
                    "index": len(aligned_words),
                    "text": word["text"],
                    "start_time": start_ms,
                    "end_time": end_ms,
                    "chunk_index": chunk["chunk_index"],
                }
            )

    manifest["device"] = resolved_device
    manifest["elapsed_seconds"] = round(time.perf_counter() - started_at, 3)
    _write_json(output_dir / "qwen-alignment-raw-returns.json", raw_returns)
    return aligned_words, manifest


def compare_word_ledgers(
    stable_words: Sequence[ASRDataSeg],
    qwen_words: Sequence[Dict],
) -> Dict:
    stable_norms = [_normalize_token(seg.text) for seg in stable_words]
    qwen_norms = [_normalize_token(str(item.get("text") or "")) for item in qwen_words]
    comparable = min(len(stable_norms), len(qwen_norms))
    matches = sum(1 for index in range(comparable) if stable_norms[index] == qwen_norms[index])
    monotonic_errors = 0
    previous_end = -1
    gaps: List[int] = []
    durations: List[int] = []
    for item in qwen_words:
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
        "qwen_word_count": len(qwen_words),
        "count_delta": len(qwen_words) - len(stable_words),
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
            "p90": sorted(positive_gaps)[int(len(positive_gaps) * 0.9)] if positive_gaps else 0,
            "max": max(positive_gaps) if positive_gaps else 0,
            "gt300": sum(gap > 300 for gap in positive_gaps),
            "gt500": sum(gap > 500 for gap in positive_gaps),
            "gt800": sum(gap > 800 for gap in positive_gaps),
        },
    }


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
        candidate = [_normalize_token(str(words[index].get("text") or "")) for index in range(start, min(len(words), start + len(target)))]
        if candidate == target:
            return start, start + len(target)
    return None


def write_preview_srt(
    stable_srt_path: Path,
    qwen_words: Sequence[Dict],
    output_path: Path,
) -> Dict:
    stable_segments = _load_srt(stable_srt_path)
    cursor = 0
    aligned = 0
    fallback = 0
    blocks: List[str] = []
    for index, seg in enumerate(stable_segments, 1):
        match = _find_word_span(seg.text, qwen_words, cursor)
        if match:
            start_index, end_index = match
            start_time = int(qwen_words[start_index]["start_time"])
            end_time = int(qwen_words[end_index - 1]["end_time"])
            cursor = end_index
            aligned += 1
        else:
            start_time = seg.start_time
            end_time = seg.end_time
            fallback += 1
        body = [seg.text]
        if seg.translated_text:
            body.append(seg.translated_text)
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
    return {"preview_segments": len(stable_segments), "aligned": aligned, "fallback": fallback}


def check_environment() -> Dict:
    import importlib.util

    result = {
        "python": sys.executable,
        "qwen_asr": importlib.util.find_spec("qwen_asr") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
        "librosa": importlib.util.find_spec("librosa") is not None,
        "numpy": importlib.util.find_spec("numpy") is not None,
        "ffmpeg": str(_find_ffmpeg()) if _find_ffmpeg() else None,
    }
    if result["torch"]:
        import torch

        result["cuda_available"] = bool(torch.cuda.is_available())
        result["cuda_device_count"] = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qwen ForcedAligner lab for FasterWhisper transcripts.")
    parser.add_argument("--audio", type=Path, help="Audio file path.")
    parser.add_argument("--stable-word-json", type=Path, help="Existing stable-ts/asr_corrected word JSON.")
    parser.add_argument("--stable-preview-srt", type=Path, help="Stable final SRT used to build qwen-aligned preview SRT.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--model", default="Qwen/Qwen3-ForcedAligner-0.6B")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--max-chunk-ms", type=int, default=240_000)
    parser.add_argument("--pad-ms", type=int, default=1_000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-env", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    env = check_environment()
    _write_json(args.output_dir / "qwen-alignment-env.json", env)
    if args.check_env:
        print(json.dumps(env, ensure_ascii=False, indent=2))
        return 0

    if not args.audio or not args.stable_word_json:
        raise SystemExit("--audio and --stable-word-json are required unless --check-env is used")

    stable_words = _load_segments_json(args.stable_word_json)
    aligned_words, manifest = run_qwen_alignment(
        audio_path=args.audio,
        stable_words=stable_words,
        output_dir=args.output_dir,
        language=args.language,
        model_name=args.model,
        device=args.device,
        dtype_name=args.dtype,
        max_chunk_ms=args.max_chunk_ms,
        pad_ms=args.pad_ms,
        dry_run=args.dry_run,
    )
    _write_json(args.output_dir / "qwen-alignment-manifest.json", manifest)

    if args.dry_run:
        print(json.dumps({"status": "dry_run", "chunk_count": manifest["chunk_count"]}, ensure_ascii=False, indent=2))
        return 0

    _write_json(args.output_dir / "qwen-word-ledger.json", aligned_words)
    report = compare_word_ledgers(stable_words, aligned_words)
    if args.stable_preview_srt:
        preview_path = args.output_dir / "qwen-aligned-preview.srt"
        report["preview_srt"] = str(preview_path)
        report["preview"] = write_preview_srt(args.stable_preview_srt, aligned_words, preview_path)
    _write_json(args.output_dir / "alignment-compare-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
