import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.utils.logger import setup_logger

logger = setup_logger("stable_ts_alignment")

WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)?|\d+(?:[.,]\d+)?")


def _project_root() -> Path:
    return PROJECT_ROOT


def _default_lab_python() -> Path:
    return Path("E:/VideoCaptioner-alignment-lab/python311/python.exe")


def _bundled_runtime_python() -> Path:
    return _project_root() / "runtime" / "python.exe"


def _stable_ts_cache_dir() -> Path:
    return _project_root() / "AppData" / "models" / "stable-ts"


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


def align_to_word_timestamps(
    audio_path: str,
    asr_data: ASRData,
    language: str = "en",
    model_name: Optional[str] = None,
    callback=None,
) -> Optional[ASRData]:
    """Return stable-ts word-level ASRData, or None when alignment is unavailable."""
    try:
        from app.common.config import cfg

        if not cfg.stable_ts_alignment_enabled.value:
            logger.info("Stable-ts alignment disabled in GUI settings")
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
        logger.info("Stable-ts alignment skipped: transcript is too short")
        return None

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


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        raise SystemExit(_run_worker(sys.argv[2]))
