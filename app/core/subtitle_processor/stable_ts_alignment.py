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
from app.core.subtitle_processor.word_timing_trust import (
    describe_word_timing_issue,
    find_implausible_word_timing_runs,
)

logger = setup_logger("stable_ts_alignment")

WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)?|\d+(?:[.,]\d+)?")
ALIGNMENT_EXPANSION_TOKEN_RE = re.compile(r"[\d$\u00a3\u20ac\u00a5%]")
ALIGNMENT_ACRONYM_RE = re.compile(r"^(?:[A-Z]\.?){2,6}[.,!?;:]?$")
EXPANSION_COMPRESSION_MIN_MS = 240
EXPANSION_COMPRESSION_MAX_RATIO = 0.5
EXPANSION_DRIFT_RECOVERY_MS = 350
EXPANSION_FALLBACK_MAX_WORDS = 24


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


def _fallback_implausible_stable_ts_updates(
    source_segments: Sequence[ASRDataSeg],
    aligned_segments: Sequence[ASRDataSeg],
    *,
    source_timing_trusted: bool,
) -> List[dict]:
    """Keep valid native times only for stable-ts compression clusters."""

    if not source_timing_trusted or not source_segments or not aligned_segments:
        return []
    source_words = [
        _normalize_word(str(getattr(segment, "text", "") or ""))
        for segment in source_segments
    ]
    aligned_words = [
        _normalize_word(str(getattr(segment, "text", "") or ""))
        for segment in aligned_segments
    ]

    fallbacks: List[dict] = []
    while True:
        timing_issues = find_implausible_word_timing_runs(aligned_segments)
        if not timing_issues:
            break
        issue = timing_issues[0]
        start_index, end_index = _expand_compressed_timing_core(
            aligned_segments,
            int(issue["start_index"]),
            int(issue["end_index"]),
            start_ms=int(issue["start_ms"]),
            end_ms=int(issue["end_ms"]),
        )
        needle = aligned_words[start_index : end_index + 1]
        if not needle or any(not word for word in needle):
            break
        source_starts = [
            index
            for index in range(len(source_words) - len(needle) + 1)
            if source_words[index : index + len(needle)] == needle
        ]
        if not source_starts:
            break
        source_start = min(
            source_starts,
            key=lambda index: abs(
                int(source_segments[index].start_time) - int(issue["start_ms"])
            )
            + abs(
                int(source_segments[index + len(needle) - 1].end_time)
                - int(issue["end_ms"])
            ),
        )
        source_slice = source_segments[source_start : source_start + len(needle)]
        acoustic_distance = abs(
            int(source_slice[0].start_time) - int(issue["start_ms"])
        ) + abs(int(source_slice[-1].end_time) - int(issue["end_ms"]))
        if acoustic_distance > 5000:
            break
        if find_implausible_word_timing_runs(source_slice):
            break
        for offset, word_id in enumerate(range(start_index, end_index + 1)):
            baseline = source_slice[offset]
            candidate = aligned_segments[word_id]
            candidate.start_time = int(baseline.start_time)
            candidate.end_time = int(baseline.end_time)
            candidate.alignment_source = "native-word-timing-fallback"
        fallbacks.append(
            {
                "code": "stable_ts_implausible_word_density_fallback",
                "fallback_word_ids": list(range(start_index, end_index + 1)),
                "source_word_ids": list(
                    range(source_start, source_start + len(needle))
                ),
                "rejected_stable_ts_range_ms": [
                    int(issue["start_ms"]),
                    int(issue["end_ms"]),
                ],
            }
        )
    return fallbacks


def _expand_compressed_timing_core(
    segments: Sequence[ASRDataSeg],
    start_index: int,
    end_index: int,
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[int, int]:
    """Include adjacent words collapsed inside the same tiny time envelope."""

    while start_index > 0:
        previous = segments[start_index - 1]
        if (
            int(previous.start_time) < start_ms
            or int(previous.end_time) > end_ms
        ):
            break
        start_index -= 1
    while end_index + 1 < len(segments):
        following = segments[end_index + 1]
        if (
            int(following.start_time) < start_ms
            or int(following.end_time) > end_ms
        ):
            break
        end_index += 1
    return start_index, end_index


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

        density_fallbacks = _fallback_implausible_stable_ts_updates(
            asr_data.segments,
            aligned.segments,
            source_timing_trusted=bool(
                getattr(asr_data, "word_timing_trusted", False)
            ),
        )
        aligned.stable_ts_density_fallbacks = density_fallbacks
        timing_issues = find_implausible_word_timing_runs(aligned.segments)
        if timing_issues:
            logger.warning(
                "Stable-ts alignment rejected: implausible local word timing: %s",
                describe_word_timing_issue(timing_issues[0]),
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
    *,
    reject_expansion_drift: bool = False,
) -> ASRData:
    if not source_segments or not aligned_words:
        return ASRData([])
    aligned_norms = [_normalize_word(str(word.get("text") or word.get("word") or "")) for word in aligned_words]
    cursor = 0
    mapped: List[ASRDataSeg] = []
    matched = 0
    for word_id, seg in enumerate(source_segments):
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
            alignment_source = "whisperx"
        else:
            start = int(seg.start_time)
            end = int(seg.end_time)
            alignment_source = "stable-ts-fallback"
        if end <= start:
            end = start + 120
        mapped_segment = ASRDataSeg(text=source_text, start_time=start, end_time=end)
        # ASRData sorts by time. Keep the frozen ledger coordinate explicitly
        # so a malformed alignment can never silently change word ownership.
        mapped_segment.word_id = word_id
        mapped_segment.alignment_source = alignment_source
        mapped.append(mapped_segment)
    expansion_fallbacks = (
        _fallback_expansion_sensitive_whisperx_updates(source_segments, mapped)
        if reject_expansion_drift
        else []
    )
    density_fallbacks = _fallback_implausible_whisperx_updates(
        source_segments,
        mapped,
    )
    monotonicity_fallbacks = _fallback_non_monotonic_whisperx_updates(
        source_segments,
        mapped,
    )
    logger.info(
        "WhisperX source text mapping completed: source=%s aligned=%s matched=%s monotonicity_fallbacks=%s",
        len(source_segments),
        len(aligned_words),
        matched,
        len(monotonicity_fallbacks),
    )
    result = ASRData(mapped)
    result.whisperx_matched_word_count = matched
    result.whisperx_expansion_fallbacks = expansion_fallbacks
    result.whisperx_density_fallbacks = density_fallbacks
    result.whisperx_monotonicity_fallbacks = monotonicity_fallbacks
    result.word_timing_trust_issues = find_implausible_word_timing_runs(
        result.segments
    )
    result.whisperx_fallback_word_count = sum(
        1
        for segment in mapped
        if getattr(segment, "alignment_source", "") != "whisperx"
    )
    return result


def _fallback_implausible_whisperx_updates(
    source_segments: Sequence[ASRDataSeg],
    mapped_segments: Sequence[ASRDataSeg],
) -> List[dict]:
    """Reject WhisperX updates that create an impossible local speech rate."""

    if len(source_segments) != len(mapped_segments):
        return []
    fallbacks: List[dict] = []
    while True:
        timing_issues = find_implausible_word_timing_runs(mapped_segments)
        if not timing_issues:
            break
        issue = timing_issues[0]
        start_index, end_index = _expand_compressed_timing_core(
            mapped_segments,
            int(issue["start_index"]),
            int(issue["end_index"]),
            start_ms=int(issue["start_ms"]),
            end_ms=int(issue["end_ms"]),
        )
        fallback_word_ids = []
        rejected_range = [int(issue["start_ms"]), int(issue["end_ms"])]
        for word_id in range(start_index, end_index + 1):
            candidate = mapped_segments[word_id]
            if getattr(candidate, "alignment_source", "") != "whisperx":
                continue
            baseline = source_segments[word_id]
            candidate.start_time = int(baseline.start_time)
            candidate.end_time = int(baseline.end_time)
            candidate.alignment_source = "stable-ts-fallback"
            candidate.whisperx_rejected_reason = (
                "whisperx_implausible_word_density_fallback"
            )
            fallback_word_ids.append(word_id)
        if fallback_word_ids:
            fallbacks.append(
                {
                    "code": "whisperx_implausible_word_density_fallback",
                    "fallback_word_ids": fallback_word_ids,
                    "rejected_whisperx_range_ms": rejected_range,
                }
            )
            continue
        break
    return fallbacks


def _is_expansion_sensitive_alignment_token(text: str) -> bool:
    token = (text or "").strip()
    return bool(
        token
        and (
            ALIGNMENT_EXPANSION_TOKEN_RE.search(token)
            or ALIGNMENT_ACRONYM_RE.fullmatch(token)
        )
    )


def _is_severely_compressed_alignment(
    baseline: ASRDataSeg,
    candidate: ASRDataSeg,
) -> bool:
    if getattr(candidate, "alignment_source", "") != "whisperx":
        return False
    baseline_text = str(getattr(baseline, "text", "") or "")
    if not _is_expansion_sensitive_alignment_token(baseline_text):
        return False
    baseline_duration = max(1, int(baseline.end_time) - int(baseline.start_time))
    candidate_duration = max(1, int(candidate.end_time) - int(candidate.start_time))
    return (
        baseline_duration - candidate_duration >= EXPANSION_COMPRESSION_MIN_MS
        and candidate_duration <= baseline_duration * EXPANSION_COMPRESSION_MAX_RATIO
    )


def _alignment_drift_from_baseline(
    baseline: ASRDataSeg,
    candidate: ASRDataSeg,
) -> tuple[int, int]:
    return (
        int(candidate.start_time) - int(baseline.start_time),
        int(candidate.end_time) - int(baseline.end_time),
    )


def _fallback_expansion_sensitive_whisperx_updates(
    source_segments: Sequence[ASRDataSeg],
    mapped_segments: Sequence[ASRDataSeg],
) -> List[dict]:
    """Reject a local drift run caused by compact written-form tokens.

    WhisperX documents that numerals and currency forms may be absent from the
    alignment dictionary. A compact token can then receive only a fraction of
    its spoken duration and pull later matched words forward until the next
    reliable acoustic anchor. Keep the frozen ledger times only for that local
    run; the first recovered word and all unrelated WhisperX updates remain.
    """
    if len(source_segments) != len(mapped_segments):
        return []

    fallbacks: List[dict] = []
    index = 0
    while index < len(mapped_segments):
        baseline = source_segments[index]
        candidate = mapped_segments[index]
        if not _is_severely_compressed_alignment(baseline, candidate):
            index += 1
            continue

        previous_alignment_source = (
            getattr(mapped_segments[index - 1], "alignment_source", "")
            if index > 0
            else ""
        )
        if previous_alignment_source == "whisperx":
            anchor_start_drift, anchor_end_drift = _alignment_drift_from_baseline(
                source_segments[index - 1],
                mapped_segments[index - 1],
            )
        else:
            anchor_start_drift = int(candidate.start_time) - int(baseline.start_time)
            anchor_end_drift = anchor_start_drift

        run_end = index
        search_end = min(len(mapped_segments), index + EXPANSION_FALLBACK_MAX_WORDS)
        for candidate_index in range(index + 1, search_end):
            next_baseline = source_segments[candidate_index]
            next_candidate = mapped_segments[candidate_index]
            next_start_drift, next_end_drift = _alignment_drift_from_baseline(
                next_baseline,
                next_candidate,
            )
            recovered = (
                getattr(next_candidate, "alignment_source", "") == "whisperx"
                and not _is_severely_compressed_alignment(next_baseline, next_candidate)
                and abs(next_start_drift - anchor_start_drift) <= EXPANSION_DRIFT_RECOVERY_MS
                and abs(next_end_drift - anchor_end_drift) <= EXPANSION_DRIFT_RECOVERY_MS
            )
            if recovered:
                break
            run_end = candidate_index

        rejected_range = [
            int(mapped_segments[index].start_time),
            int(mapped_segments[run_end].end_time),
        ]
        fallback_word_ids: List[int] = []
        for fallback_index in range(index, run_end + 1):
            fallback_candidate = mapped_segments[fallback_index]
            if getattr(fallback_candidate, "alignment_source", "") != "whisperx":
                continue
            fallback_baseline = source_segments[fallback_index]
            fallback_candidate.start_time = int(fallback_baseline.start_time)
            fallback_candidate.end_time = int(fallback_baseline.end_time)
            fallback_candidate.alignment_source = "stable-ts-fallback"
            fallback_candidate.whisperx_rejected_reason = (
                "whisperx_expansion_compression_fallback"
            )
            fallback_word_ids.append(fallback_index)

        if fallback_word_ids:
            fallbacks.append(
                {
                    "code": "whisperx_expansion_compression_fallback",
                    "trigger_word_id": index,
                    "trigger_word": str(getattr(candidate, "text", "") or ""),
                    "fallback_word_ids": fallback_word_ids,
                    "baseline_range_ms": [
                        int(source_segments[index].start_time),
                        int(source_segments[run_end].end_time),
                    ],
                    "rejected_whisperx_range_ms": rejected_range,
                }
            )
        index = run_end + 1

    return fallbacks


def _is_unresolvable_word_order_inversion(
    left: ASRDataSeg,
    right: ASRDataSeg,
) -> bool:
    """Return whether final boundary reconciliation cannot preserve word order."""
    # ``reconcile_frozen_word_ledger`` can safely reconcile ordinary envelope
    # overlaps. It cannot repair a following word that has already ended at or
    # before the preceding word begins without creating an invalid duration.
    return int(right.end_time) <= int(left.start_time) + 1


def _fallback_non_monotonic_whisperx_updates(
    source_segments: Sequence[ASRDataSeg],
    mapped_segments: Sequence[ASRDataSeg],
) -> List[dict]:
    """Reject only WhisperX updates that invert an otherwise valid ledger.

    A frozen stable-ts ledger is the source of truth for word ownership and
    ordering. WhisperX may refine any matched word, while unmatched words keep
    their baseline time. When that hybrid creates an unrecoverable inversion,
    retain the smallest possible stable-ts fallback instead of asking the final
    cue builder to distort words or reorder the ledger.
    """
    if len(source_segments) != len(mapped_segments):
        return []

    fallbacks: List[dict] = []
    while True:
        repaired = False
        for index, (left, right) in enumerate(zip(mapped_segments, mapped_segments[1:])):
            if not _is_unresolvable_word_order_inversion(left, right):
                continue

            baseline_left = source_segments[index]
            baseline_right = source_segments[index + 1]
            # Do not mask a pre-existing stable-ts issue. The final ledger
            # reconciliation remains responsible for reporting it.
            if _is_unresolvable_word_order_inversion(baseline_left, baseline_right):
                continue

            alternatives = []
            for candidate_index, candidate, baseline in (
                (index, left, baseline_left),
                (index + 1, right, baseline_right),
            ):
                if getattr(candidate, "alignment_source", "") != "whisperx":
                    continue
                old_range = (int(candidate.start_time), int(candidate.end_time))
                candidate.start_time = int(baseline.start_time)
                candidate.end_time = int(baseline.end_time)
                resolves = not _is_unresolvable_word_order_inversion(
                    mapped_segments[index], mapped_segments[index + 1]
                )
                candidate.start_time, candidate.end_time = old_range
                if resolves:
                    deviation = abs(old_range[0] - int(baseline.start_time)) + abs(
                        old_range[1] - int(baseline.end_time)
                    )
                    alternatives.append((deviation, candidate_index, baseline))

            if not alternatives:
                continue

            # Prefer reverting the update that moved furthest from the frozen
            # baseline. The index tie-break keeps repeated runs deterministic.
            _, candidate_index, baseline = sorted(
                alternatives,
                key=lambda value: (-value[0], value[1]),
            )[0]
            candidate = mapped_segments[candidate_index]
            candidate_range = [int(candidate.start_time), int(candidate.end_time)]
            baseline_range = [int(baseline.start_time), int(baseline.end_time)]
            candidate.start_time, candidate.end_time = baseline_range
            candidate.alignment_source = "stable-ts-fallback"
            candidate.whisperx_rejected_reason = "whisperx_monotonicity_fallback"
            fallbacks.append(
                {
                    "code": "whisperx_monotonicity_fallback",
                    "word_id": candidate_index,
                    "word": str(getattr(candidate, "text", "") or ""),
                    "baseline_range_ms": baseline_range,
                    "rejected_whisperx_range_ms": candidate_range,
                    "conflicting_word_ids": [index, index + 1],
                }
            )
            repaired = True
            break
        if not repaired:
            return fallbacks


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
        if getattr(aligned, "word_timing_trust_issues", None):
            logger.warning(
                "WhisperX alignment rejected: implausible local word timing: %s",
                describe_word_timing_issue(aligned.word_timing_trust_issues[0]),
            )
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


def align_frozen_word_ledger_with_whisperx(
    audio_path: str,
    alignment_source: ASRData,
    frozen_word_ledger: ASRData,
    language: str = "en",
    callback=None,
) -> Optional[ASRData]:
    """Update only frozen ledger word times with WhisperX evidence.

    ``alignment_source`` supplies natural ASR phrases to WhisperX.  The result
    is mapped monotonically back to ``frozen_word_ledger`` by its existing word
    order.  Unmatched individual words retain their stable-ts times; no final
    subtitle string is ever remapped by text in this path.
    """
    language = (language or "").lower()
    if language not in {"en", "english"}:
        logger.info("WhisperX ledger alignment skipped for non-English language: %s", language)
        return None
    if not alignment_source or not alignment_source.segments:
        logger.warning("WhisperX ledger alignment skipped: alignment source is empty")
        return None
    if not frozen_word_ledger or not frozen_word_ledger.segments:
        logger.warning("WhisperX ledger alignment skipped: frozen word ledger is empty")
        return None

    aligned_words = _run_whisperx_words(audio_path, alignment_source, language, callback=callback)
    if not aligned_words:
        return None
    mapped = _make_whisperx_word_segments(
        frozen_word_ledger.segments,
        aligned_words,
        reject_expansion_drift=True,
    )
    expected_word_ids = set(range(len(frozen_word_ledger.segments)))
    returned_word_ids = {
        int(getattr(segment, "word_id", -1))
        for segment in mapped.segments
    }
    if returned_word_ids != expected_word_ids:
        logger.warning(
            "WhisperX ledger alignment rejected: word ID set mismatch expected=%s returned=%s",
            len(expected_word_ids),
            len(returned_word_ids),
        )
        return None
    timing_issues = list(getattr(mapped, "word_timing_trust_issues", []) or [])
    if timing_issues:
        logger.warning(
            "WhisperX ledger alignment rejected: implausible local word timing: %s",
            describe_word_timing_issue(timing_issues[0]),
        )
        return None
    mapped.whisperx_alignment_source_word_count = len(alignment_source.segments)
    logger.info(
        "WhisperX frozen ledger alignment completed: words=%s matched=%s fallback=%s",
        len(mapped.segments),
        getattr(mapped, "whisperx_matched_word_count", 0),
        getattr(mapped, "whisperx_fallback_word_count", 0),
    )
    return mapped


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
