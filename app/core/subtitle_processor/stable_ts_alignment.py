import json
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.utils.logger import setup_logger

logger = setup_logger("stable_ts_alignment")

WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)?|\d+(?:[.,]\d+)?")


def _load_asr_classes():
    module_path = PROJECT_ROOT / "app" / "core" / "bk_asr" / "asr_data.py"
    spec = importlib.util.spec_from_file_location("_vc_asr_data", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load ASR data module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ASRData, module.ASRDataSeg


ASRData, ASRDataSeg = _load_asr_classes()


def _project_root() -> Path:
    return PROJECT_ROOT


def _default_lab_python() -> Path:
    return Path("E:/VideoCaptioner-alignment-lab/python311/python.exe")


def _bundled_runtime_python() -> Path:
    return _project_root() / "runtime" / "python.exe"


def _stable_ts_cache_dir() -> Path:
    return _project_root() / "AppData" / "models" / "stable-ts"


def _whisperx_runtime_python() -> Path:
    return _project_root() / "whisperx-runtime" / "Scripts" / "python.exe"


def _is_python_executable(path: Path) -> bool:
    return path.name.lower() in {"python.exe", "pythonw.exe", "python"}


def _find_stable_ts_python() -> Optional[Path]:
    env_path = os.getenv("VIDEOCAPTIONER_STABLE_TS_PYTHON")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(_bundled_runtime_python())
    candidates.append(_default_lab_python())
    current_executable = Path(sys.executable)
    if _is_python_executable(current_executable):
        candidates.append(current_executable)

    for candidate in candidates:
        if not candidate.exists():
            continue
        if not _is_python_executable(candidate):
            logger.warning("Stable-ts python candidate skipped: not a Python executable: %s", candidate)
            continue
        try:
            result = subprocess.run(
                [str(candidate), "-c", "import stable_whisper"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                timeout=20,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


def _find_whisperx_python() -> Optional[Path]:
    env_path = os.getenv("VIDEOCAPTIONER_WHISPERX_PYTHON")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(_whisperx_runtime_python())
    current_executable = Path(sys.executable)
    if _is_python_executable(current_executable):
        candidates.append(current_executable)

    for candidate in candidates:
        if not candidate.exists():
            continue
        if not _is_python_executable(candidate):
            logger.warning("WhisperX python candidate skipped: not a Python executable: %s", candidate)
            continue
        try:
            result = subprocess.run(
                [str(candidate), "-c", "import whisperx, torch"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                timeout=20,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


def _normalize_word(text: str) -> str:
    found = WORD_RE.findall(text or "")
    return found[0].lower() if found else (text or "").strip().lower()


def _collect_transcript(asr_data: ASRData) -> str:
    parts = []
    for seg in asr_data.segments:
        text = (seg.text or "").strip()
        if text:
            parts.append(text)
    transcript = " ".join(parts)
    transcript = re.sub(r"\s+", " ", transcript).strip()
    return transcript


def _make_word_segments(words: List[dict]) -> ASRData:
    segments: List[ASRDataSeg] = []
    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        start = int(round(float(word["start"]) * 1000))
        end = int(round(float(word["end"]) * 1000))
        if end <= start:
            end = start + 120
        segments.append(ASRDataSeg(text=text, start_time=start, end_time=end))
    return ASRData(segments)


def _configured_alignment_backend() -> str:
    try:
        from app.common.config import cfg

        return str(cfg.timeline_alignment_backend.value or "stable-ts").strip().lower()
    except Exception:
        return os.getenv("VIDEOCAPTIONER_ALIGNMENT_BACKEND", "stable-ts").strip().lower()


def align_to_word_timestamps(
    audio_path: str,
    asr_data: ASRData,
    language: str = "en",
    model_name: Optional[str] = None,
    callback=None,
) -> Optional[ASRData]:
    """Return aligned word-level ASRData, or None when alignment is unavailable."""
    try:
        from app.common.config import cfg

        if not cfg.stable_ts_alignment_enabled.value:
            logger.info("Timeline alignment disabled in GUI settings")
            return None
        configured_model = cfg.stable_ts_alignment_model.value
    except Exception:
        configured_model = None

    if os.getenv("VIDEOCAPTIONER_STABLE_TS", "1").strip().lower() in {"0", "false", "off", "no"}:
        logger.info("Stable-ts alignment disabled by VIDEOCAPTIONER_STABLE_TS")
        return None

    language = (language or "").lower()
    if language not in {"en", "english"}:
        logger.info("Stable-ts alignment skipped for non-English language: %s", language)
        return None

    transcript = _collect_transcript(asr_data)
    if len(WORD_RE.findall(transcript)) < 3:
        logger.info("Timeline alignment skipped: transcript is too short")
        return None

    backend = os.getenv("VIDEOCAPTIONER_ALIGNMENT_BACKEND", _configured_alignment_backend()).strip().lower()
    if backend == "whisperx":
        aligned = _align_with_whisperx(audio_path, asr_data, language, transcript, callback=callback)
        if aligned and aligned.has_data():
            return aligned
        logger.warning("WhisperX alignment unavailable; falling back to stable-ts")
    elif backend == "whisperx-time-only":
        logger.info("WhisperX time-only selected; using stable-ts for cutting word timestamps")

    python_path = _find_stable_ts_python()
    if not python_path:
        logger.warning("Stable-ts alignment skipped: stable_whisper is not installed")
        return None

    if callback:
        callback(92, "stable-ts词级对齐...")

    model_name = (
        model_name
        or os.getenv("VIDEOCAPTIONER_STABLE_TS_MODEL")
        or configured_model
        or "large-v3-turbo"
    )
    cache_dir = Path(os.getenv("VIDEOCAPTIONER_STABLE_TS_CACHE", str(_stable_ts_cache_dir())))
    worker = Path(__file__).resolve()

    with tempfile.TemporaryDirectory(prefix="vc_stable_ts_") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / "input.json"
        output_path = tmp_dir / "words.json"
        input_path.write_text(
            json.dumps(
                {
                    "audio_path": str(audio_path),
                    "transcript": transcript,
                    "language": "en",
                    "model_name": model_name,
                    "cache_dir": str(cache_dir),
                    "output_path": str(output_path),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(_project_root())
        cmd = [str(python_path), str(worker), "--worker", str(input_path)]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            logger.warning("Stable-ts alignment failed: %s", result.stderr[-2000:])
            return None
        if not output_path.exists():
            logger.warning("Stable-ts alignment failed: worker produced no output")
            return None

        words = json.loads(output_path.read_text(encoding="utf-8"))
        aligned = _make_word_segments(words)
        if len(aligned.segments) < max(3, int(len(WORD_RE.findall(transcript)) * 0.6)):
            logger.warning(
                "Stable-ts alignment rejected: too few words, got %s",
                len(aligned.segments),
            )
            return None

        zeroish = sum(1 for seg in aligned.segments if seg.end_time <= seg.start_time + 5)
        logger.info(
            "Stable-ts alignment completed: words=%s zeroish=%s model=%s",
            len(aligned.segments),
            zeroish,
            model_name,
        )
        if callback:
            callback(98, "stable-ts词级对齐完成")
        return aligned


def _asr_payload_segments(asr_data: ASRData) -> List[dict]:
    segments = []
    for index, seg in enumerate(asr_data.segments):
        text = (seg.text or "").strip()
        if not text:
            continue
        segments.append(
            {
                "index": index,
                "text": text,
                "norm": _normalize_word(text),
                "start": max(0, int(seg.start_time)) / 1000.0,
                "end": max(0, int(seg.end_time)) / 1000.0,
                "start_ms": int(seg.start_time),
                "end_ms": int(seg.end_time),
            }
        )
    return segments


def _make_whisperx_word_segments(
    source_segments: Sequence[ASRDataSeg],
    aligned_words: Sequence[dict],
) -> ASRData:
    if not source_segments or not aligned_words:
        return ASRData([])
    aligned_norms = [_normalize_word(str(word.get("text") or word.get("word") or "")) for word in aligned_words]
    cursor = 0
    mapped: List[ASRDataSeg] = []
    matched = 0
    for seg in source_segments:
        source_text = (seg.text or "").strip()
        source_norm = _normalize_word(source_text)
        matched_index = None
        if source_norm:
            for index in range(cursor, min(len(aligned_words), cursor + 8)):
                if aligned_norms[index] == source_norm:
                    matched_index = index
                    break
        if matched_index is not None:
            word = aligned_words[matched_index]
            start = int(round(float(word["start"]) * 1000))
            end = int(round(float(word["end"]) * 1000))
            cursor = matched_index + 1
            matched += 1
        else:
            start = int(seg.start_time)
            end = int(seg.end_time)
        if end <= start:
            end = start + 120
        mapped.append(ASRDataSeg(text=source_text, start_time=start, end_time=end))
    logger.info(
        "WhisperX source text mapping completed: source=%s aligned=%s matched=%s",
        len(source_segments),
        len(aligned_words),
        matched,
    )
    return ASRData(mapped)


def _align_with_whisperx(
    audio_path: str,
    asr_data: ASRData,
    language: str,
    transcript: str,
    callback=None,
) -> Optional[ASRData]:
    python_path = _find_whisperx_python()
    if not python_path:
        logger.warning("WhisperX alignment skipped: whisperx runtime is not installed")
        return None
    if callback:
        callback(92, "WhisperX词级对齐...")

    worker = Path(__file__).resolve()
    source_segments = _asr_payload_segments(asr_data)
    with tempfile.TemporaryDirectory(prefix="vc_whisperx_") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / "input.json"
        output_path = tmp_dir / "words.json"
        input_path.write_text(
            json.dumps(
                {
                    "audio_path": str(audio_path),
                    "segments": source_segments,
                    "language": "en",
                    "device": os.getenv("VIDEOCAPTIONER_WHISPERX_DEVICE", "cuda"),
                    "max_chunk_ms": int(os.getenv("VIDEOCAPTIONER_WHISPERX_MAX_CHUNK_MS", "30000")),
                    "interpolate_method": os.getenv("VIDEOCAPTIONER_WHISPERX_INTERPOLATE", "nearest"),
                    "output_path": str(output_path),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(_project_root())
        cmd = [str(python_path), str(worker), "--worker-whisperx", str(input_path)]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            logger.warning("WhisperX alignment failed: %s", result.stderr[-2000:])
            return None
        if not output_path.exists():
            logger.warning("WhisperX alignment failed: worker produced no output")
            return None
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        words = payload.get("words") or []
        aligned = _make_whisperx_word_segments(asr_data.segments, words)
        expected_words = len(WORD_RE.findall(transcript))
        if len(words) < max(3, int(expected_words * 0.6)):
            logger.warning("WhisperX alignment rejected: too few aligned words, got %s", len(words))
            return None
        zeroish = sum(1 for seg in aligned.segments if seg.end_time <= seg.start_time + 5)
        logger.info(
            "WhisperX alignment completed: raw_words=%s mapped_words=%s zeroish=%s elapsed=%s device=%s",
            len(words),
            len(aligned.segments),
            zeroish,
            payload.get("elapsed_seconds"),
            payload.get("device"),
        )
        if callback:
            callback(98, "WhisperX词级对齐完成")
        return aligned


def align_subtitle_segments_with_whisperx_time_only(
    audio_path: str,
    subtitle_data: ASRData,
    language: str = "en",
    callback=None,
    lead_in_ms: int = 40,
    tail_padding_ms: int = 260,
    min_gap_ms: int = 40,
    min_duration_ms: int = 700,
) -> Optional[ASRData]:
    """Return subtitle_data with WhisperX-derived times while preserving text.

    This is intentionally separate from the word timestamp backend used for
    stable cutting. It maps each final subtitle line to a monotonic range of
    WhisperX words and only replaces start/end times.
    """
    language = (language or "").lower()
    if language not in {"en", "english"}:
        logger.info("WhisperX time-only skipped for non-English language: %s", language)
        return None
    if not subtitle_data or not subtitle_data.segments:
        return None
    transcript = _collect_transcript(subtitle_data)
    if len(WORD_RE.findall(transcript)) < 3:
        logger.info("WhisperX time-only skipped: transcript is too short")
        return None
    frozen = _make_frozen_word_timed_subtitle_segments(
        subtitle_data.segments,
        lead_in_ms=lead_in_ms,
        tail_padding_ms=tail_padding_ms,
        min_duration_ms=min_duration_ms,
    )
    if frozen is not None:
        _repair_subtitle_timing_sequence(frozen.segments, min_gap_ms=min_gap_ms)
        _pad_short_subtitle_timing_sequence(
            frozen.segments,
            min_gap_ms=min_gap_ms,
            min_duration_ms=min_duration_ms,
        )
        logger.info(
            "WhisperX time-only skipped: using frozen stable word timings for %s subtitles",
            len(frozen.segments),
        )
        return frozen
    aligned_words = _run_whisperx_words(audio_path, subtitle_data, language, callback=callback)
    if not aligned_words:
        return None
    remapped = _make_whisperx_subtitle_segments(
        subtitle_data.segments,
        aligned_words,
        lead_in_ms=lead_in_ms,
        tail_padding_ms=tail_padding_ms,
        min_duration_ms=min_duration_ms,
    )
    if not remapped.segments:
        return None
    if not _whisperx_mapping_is_complete(remapped, subtitle_data.segments):
        return None
    _repair_subtitle_timing_sequence(remapped.segments, min_gap_ms=min_gap_ms)
    _pad_short_subtitle_timing_sequence(
        remapped.segments,
        min_gap_ms=min_gap_ms,
        min_duration_ms=min_duration_ms,
    )
    changed = sum(
        1
        for old, new in zip(subtitle_data.segments, remapped.segments)
        if int(old.start_time) != int(new.start_time) or int(old.end_time) != int(new.end_time)
    )
    logger.info(
        "WhisperX time-only mapping completed: subtitles=%s changed=%s",
        len(remapped.segments),
        changed,
    )
    return remapped


def _make_frozen_word_timed_subtitle_segments(
    source_segments: Sequence[ASRDataSeg],
    lead_in_ms: int,
    tail_padding_ms: int,
    min_duration_ms: int,
) -> Optional[ASRData]:
    if not source_segments:
        return None
    if not all(
        hasattr(seg, "stable_word_start_ms") and hasattr(seg, "stable_word_end_ms")
        for seg in source_segments
    ):
        return None

    mapped: List[ASRDataSeg] = []
    for seg in source_segments:
        raw_start = int(getattr(seg, "stable_word_start_ms"))
        raw_end = int(getattr(seg, "stable_word_end_ms"))
        start = max(0, raw_start - int(lead_in_ms))
        end = max(raw_end + int(tail_padding_ms), start + 1)
        if end - start < int(min_duration_ms):
            end = start + int(min_duration_ms)
        copied = ASRDataSeg(
            text=seg.text,
            translated_text=seg.translated_text,
            start_time=start,
            end_time=end,
        )
        for attr in (
            "subtitle_id",
            "word_start",
            "word_end",
            "stable_word_start_ms",
            "stable_word_end_ms",
        ):
            if hasattr(seg, attr):
                setattr(copied, attr, getattr(seg, attr))
        mapped.append(copied)
    result = ASRData(mapped)
    result.whisperx_unmatched_subtitles = []
    result.whisperx_matched_subtitle_count = len(mapped)
    result.used_frozen_stable_word_timing = True
    return result


def _run_whisperx_words(
    audio_path: str,
    asr_data: ASRData,
    language: str,
    callback=None,
) -> List[dict]:
    python_path = _find_whisperx_python()
    if not python_path:
        logger.warning("WhisperX time-only skipped: whisperx runtime is not installed")
        return []
    if callback:
        callback(92, "WhisperX最终时间轴对齐...")

    worker = Path(__file__).resolve()
    source_segments = _asr_payload_segments(asr_data)
    with tempfile.TemporaryDirectory(prefix="vc_whisperx_time_only_") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / "input.json"
        output_path = tmp_dir / "words.json"
        input_path.write_text(
            json.dumps(
                {
                    "audio_path": str(audio_path),
                    "segments": source_segments,
                    "language": "en",
                    "device": os.getenv("VIDEOCAPTIONER_WHISPERX_DEVICE", "cuda"),
                    "max_chunk_ms": int(os.getenv("VIDEOCAPTIONER_WHISPERX_MAX_CHUNK_MS", "30000")),
                    "interpolate_method": os.getenv("VIDEOCAPTIONER_WHISPERX_INTERPOLATE", "nearest"),
                    "output_path": str(output_path),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = str(_project_root())
        cmd = [str(python_path), str(worker), "--worker-whisperx", str(input_path)]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            logger.warning("WhisperX time-only failed: %s", result.stderr[-2000:])
            return []
        if not output_path.exists():
            logger.warning("WhisperX time-only failed: worker produced no output")
            return []
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        words = payload.get("words") or []
        expected_words = len(WORD_RE.findall(_collect_transcript(asr_data)))
        if len(words) < max(3, int(expected_words * 0.6)):
            logger.warning("WhisperX time-only rejected: too few aligned words, got %s", len(words))
            return []
        logger.info(
            "WhisperX time-only raw alignment completed: raw_words=%s elapsed=%s device=%s",
            len(words),
            payload.get("elapsed_seconds"),
            payload.get("device"),
        )
        if callback:
            callback(98, "WhisperX最终时间轴完成")
        return words


def _subtitle_tokens(text: str) -> List[str]:
    return [_normalize_word(token) for token in WORD_RE.findall(text or "") if _normalize_word(token)]


def _find_token_sequence(
    aligned_norms: Sequence[str],
    tokens: Sequence[str],
    cursor: int,
    window: int = 40,
) -> Optional[tuple[int, int]]:
    if not tokens:
        return None
    max_start = min(len(aligned_norms), cursor + window)
    for start in range(cursor, max_start):
        if aligned_norms[start : start + len(tokens)] == list(tokens):
            return start, start + len(tokens)
    # Some ASR punctuation/number normalization differs. Fall back to a compact
    # local subsequence match without moving backwards.
    best: Optional[tuple[int, int, int]] = None
    local_end = min(len(aligned_norms), cursor + max(window, len(tokens) + 20))
    for start in range(cursor, local_end):
        ti = 0
        end = start
        for index in range(start, local_end):
            if aligned_norms[index] == tokens[ti]:
                ti += 1
                end = index + 1
                if ti == len(tokens):
                    span = end - start
                    best = (start, end, span)
                    break
        if best is not None:
            break
    if best is None:
        return None
    return best[0], best[1]


def _make_whisperx_subtitle_segments(
    source_segments: Sequence[ASRDataSeg],
    aligned_words: Sequence[dict],
    lead_in_ms: int,
    tail_padding_ms: int,
    min_duration_ms: int,
) -> ASRData:
    aligned_norms = [
        _normalize_word(str(word.get("text") or word.get("word") or ""))
        for word in aligned_words
    ]
    mapped: List[ASRDataSeg] = []
    unmatched: List[dict] = []
    cursor = 0
    matched = 0
    for subtitle_index, seg in enumerate(source_segments, 1):
        tokens = _subtitle_tokens(seg.text or "")
        word_range = _find_token_sequence(aligned_norms, tokens, cursor)
        if word_range:
            start_index, end_index = word_range
            first = aligned_words[start_index]
            last = aligned_words[end_index - 1]
            start = int(round(float(first["start"]) * 1000)) - int(lead_in_ms)
            end = int(round(float(last["end"]) * 1000)) + int(tail_padding_ms)
            cursor = end_index
            matched += 1
        else:
            unmatched.append(
                {
                    "index": subtitle_index,
                    "text": seg.text,
                    "token_count": len(tokens),
                    "start_time": int(seg.start_time),
                    "end_time": int(seg.end_time),
                }
            )
            start = int(seg.start_time)
            end = int(seg.end_time)
        start = max(0, start)
        if end <= start:
            end = start + max(120, int(min_duration_ms))
        elif end - start < int(min_duration_ms):
            end = start + int(min_duration_ms)
        mapped.append(
            ASRDataSeg(
                text=seg.text,
                translated_text=seg.translated_text,
                start_time=start,
                end_time=end,
            )
        )
    logger.info(
        "WhisperX subtitle time-only source mapping: subtitles=%s matched=%s raw_words=%s",
        len(source_segments),
        matched,
        len(aligned_words),
    )
    result = ASRData(mapped)
    result.whisperx_unmatched_subtitles = unmatched
    result.whisperx_matched_subtitle_count = matched
    return result


def _whisperx_mapping_is_complete(
    mapped: ASRData,
    source_segments: Sequence[ASRDataSeg],
) -> bool:
    unmatched = list(getattr(mapped, "whisperx_unmatched_subtitles", []) or [])
    if unmatched:
        logger.warning(
            "WhisperX time-only rejected: %s subtitles were not fully mapped; first=%s",
            len(unmatched),
            unmatched[0],
        )
        return False
    matched = int(getattr(mapped, "whisperx_matched_subtitle_count", 0) or 0)
    if matched != len(source_segments):
        logger.warning(
            "WhisperX time-only rejected: matched subtitle count mismatch %s/%s",
            matched,
            len(source_segments),
        )
        return False
    return True


def _repair_subtitle_timing_sequence(
    segments: Sequence[ASRDataSeg],
    min_gap_ms: int,
) -> None:
    for index in range(len(segments) - 1):
        current = segments[index]
        nxt = segments[index + 1]
        latest_end = max(current.start_time + 120, nxt.start_time - int(min_gap_ms))
        if current.end_time > latest_end:
            current.end_time = latest_end
        if nxt.start_time <= current.end_time:
            nxt.start_time = current.end_time + int(min_gap_ms)
        if nxt.end_time <= nxt.start_time:
            nxt.end_time = nxt.start_time + 120


def _pad_short_subtitle_timing_sequence(
    segments: Sequence[ASRDataSeg],
    min_gap_ms: int,
    min_duration_ms: int,
) -> None:
    """Extend ultra-short mapped subtitles without changing text or order."""
    if not segments:
        return
    gap = int(min_gap_ms)
    target_duration = int(min_duration_ms)
    for index, seg in enumerate(segments):
        start = max(0, int(seg.start_time))
        end = max(start + 1, int(seg.end_time))
        if end - start >= target_duration:
            continue
        previous_limit = (
            max(0, int(segments[index - 1].end_time)) + gap
            if index > 0
            else 0
        )
        next_limit = (
            max(0, int(segments[index + 1].start_time)) - gap
            if index + 1 < len(segments)
            else None
        )

        desired_end = start + target_duration
        if next_limit is None or desired_end <= next_limit:
            seg.start_time = start
            seg.end_time = desired_end
            continue

        if index + 1 < len(segments):
            nxt = segments[index + 1]
            shifted_next_start = desired_end + gap
            next_min_duration = max(800, target_duration)
            if int(nxt.end_time) - shifted_next_start >= next_min_duration:
                seg.start_time = start
                seg.end_time = desired_end
                nxt.start_time = shifted_next_start
                continue

        target_start = end - target_duration
        if target_start >= previous_limit:
            seg.start_time = target_start
            seg.end_time = end
            continue

        span_end = max(end, next_limit)
        if span_end - previous_limit > end - start:
            seg.start_time = previous_limit
            seg.end_time = span_end


def _worker_extract_words(result) -> List[dict]:
    words: List[dict] = []
    for seg in result.segments:
        for word in getattr(seg, "words", None) or []:
            raw = getattr(word, "word", "")
            token = _normalize_word(raw)
            if not token:
                continue
            start = float(getattr(word, "start", 0.0))
            end = float(getattr(word, "end", start))
            words.append(
                {
                    "i": len(words),
                    "text": raw.strip(),
                    "norm": token,
                    "start": start,
                    "end": end,
                    "duration": max(0.0, end - start),
                }
            )
    return words


def _worker_find_ffmpeg() -> Optional[Path]:
    candidates = [
        _project_root() / "resource" / "bin" / "ffmpeg.exe",
        _project_root() / "resource" / "bin" / "Faster-Whisper-XXL" / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _worker_make_whisperx_chunks(segments: Sequence[Dict], max_chunk_ms: int) -> List[dict]:
    if not segments:
        return []
    chunks: List[dict] = []
    start_index = 0
    while start_index < len(segments):
        chunk_start_ms = int(segments[start_index].get("start_ms", 0))
        end_index = start_index
        while end_index + 1 < len(segments):
            candidate_end_ms = int(segments[end_index + 1].get("end_ms", chunk_start_ms))
            if candidate_end_ms - chunk_start_ms > max_chunk_ms:
                break
            end_index += 1
        chunk_segments = list(segments[start_index : end_index + 1])
        chunks.append(
            {
                "start": float(chunk_segments[0].get("start", 0.0)),
                "end": float(chunk_segments[-1].get("end", chunk_segments[0].get("start", 0.0))),
                "text": " ".join(str(seg.get("text") or "").strip() for seg in chunk_segments if str(seg.get("text") or "").strip()),
            }
        )
        start_index = end_index + 1
    return chunks


def _worker_extract_whisperx_words(result: Dict) -> List[dict]:
    words: List[dict] = []
    for segment in result.get("segments", []) or []:
        for word in segment.get("words", []) or []:
            text = str(word.get("word") or word.get("text") or "").strip()
            if not text or "start" not in word or "end" not in word:
                continue
            start = float(word["start"])
            end = float(word["end"])
            if end <= start:
                end = start + 0.02
            words.append(
                {
                    "i": len(words),
                    "text": text,
                    "norm": _normalize_word(text),
                    "start": start,
                    "end": end,
                    "duration": max(0.0, end - start),
                    "score": word.get("score"),
                }
            )
    return words


def _run_worker(input_path: str) -> int:
    import stable_whisper
    import torch

    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    cache_dir = Path(payload["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    device = os.getenv("VIDEOCAPTIONER_STABLE_TS_DEVICE")
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model = stable_whisper.load_model(
        payload["model_name"],
        device=device,
        download_root=str(cache_dir),
    )
    result = model.align(
        payload["audio_path"],
        payload["transcript"],
        language=payload.get("language") or "en",
        fast_mode=False,
    )
    if result is None:
        raise RuntimeError("stable-ts alignment returned no result")
    words = _worker_extract_words(result)
    Path(payload["output_path"]).write_text(
        json.dumps(words, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


def _run_whisperx_worker(input_path: str) -> int:
    import time

    import torch
    import whisperx

    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    ffmpeg = _worker_find_ffmpeg()
    if ffmpeg:
        os.environ["PATH"] = str(ffmpeg.parent) + os.pathsep + os.environ.get("PATH", "")

    device = payload.get("device") or "cuda"
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"

    started_at = time.perf_counter()
    chunks = _worker_make_whisperx_chunks(
        payload.get("segments") or [],
        int(payload.get("max_chunk_ms") or 30000),
    )
    audio = whisperx.load_audio(str(payload["audio_path"]))
    model_a, metadata = whisperx.load_align_model(
        language_code=payload.get("language") or "en",
        device=device,
    )
    result = whisperx.align(
        chunks,
        model_a,
        metadata,
        audio,
        device,
        interpolate_method=payload.get("interpolate_method") or "nearest",
        return_char_alignments=False,
    )
    words = _worker_extract_whisperx_words(result)
    output = {
        "backend": "whisperx",
        "device": device,
        "chunk_count": len(chunks),
        "word_count": len(words),
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "ffmpeg": str(ffmpeg) if ffmpeg else None,
        "words": words,
    }
    Path(payload["output_path"]).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        raise SystemExit(_run_worker(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--worker-whisperx":
        raise SystemExit(_run_whisperx_worker(sys.argv[2]))
