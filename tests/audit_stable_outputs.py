import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRData


WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+(?:\.\d+)?")


def pick_bilingual_original_top_srt(subtitle_dir: Path) -> Path | None:
    manifest = subtitle_dir / "stable-final-manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            path = Path(data.get("paths", {}).get("original_top_srt", ""))
            if path.exists() and path.stat().st_size > 0:
                return path
        except Exception:
            pass

    candidates: list[Path] = []
    for path in subtitle_dir.glob("*.srt"):
        if path.name.startswith("stable-final") or path.name.endswith(
            ".bak-before-display-fix"
        ):
            continue
        text = path.read_text(encoding="utf-8-sig", errors="ignore")[:700]
        first_block = text.split("\n\n", 1)[0]
        lines = [line.strip() for line in first_block.splitlines() if line.strip()]
        if len(lines) < 4:
            continue
        if re.search(r"[A-Za-z]", lines[2]) and re.search(r"[\u4e00-\u9fff]", lines[3]):
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def audit_srt(
    path: Path,
    max_words: int = 14,
    gap_warning_ms: int = 1200,
    gap_error_ms: int = 1500,
) -> dict:
    data = ASRData.from_srt(path.read_text(encoding="utf-8-sig", errors="ignore"))
    gap_warnings = []
    gap_errors = []
    shorts = []
    overlong = []
    missing_zh = []
    previous_end = None
    for index, segment in enumerate(data.segments, 1):
        if previous_end is not None:
            gap_ms = segment.start_time - previous_end
            if gap_ms > gap_warning_ms:
                item = (
                    {
                        "index": index,
                        "gap_ms": gap_ms,
                        "from_ms": previous_end,
                        "to_ms": segment.start_time,
                    }
                )
                if gap_ms > gap_error_ms:
                    gap_errors.append(item)
                else:
                    gap_warnings.append(item)
        duration = segment.end_time - segment.start_time
        if duration < 900:
            shorts.append(
                {
                    "index": index,
                    "duration_ms": duration,
                    "text": segment.text,
                }
            )
        word_count = len(WORD_RE.findall(segment.text or ""))
        if word_count > max_words:
            overlong.append(
                {
                    "index": index,
                    "word_count": word_count,
                    "text": segment.text,
                }
            )
        if (segment.text or "").strip() and not (segment.translated_text or "").strip():
            missing_zh.append({"index": index, "text": segment.text})
        previous_end = segment.end_time

    status = "PASS"
    if gap_errors or overlong or missing_zh:
        status = "ERROR"
    elif gap_warnings or shorts:
        status = "WARNING"
    return {
        "path": str(path),
        "status": status,
        "count": len(data.segments),
        "gap_errors": gap_errors,
        "gap_warnings": gap_warnings,
        "shorts": shorts,
        "overlong": overlong,
        "missing_zh": missing_zh,
    }


def main() -> int:
    names = sys.argv[1:] or ["222", "777", "999"]
    results = {}
    for name in names:
        subtitle_dir = ROOT / "work-dir" / name / "subtitle"
        path = pick_bilingual_original_top_srt(subtitle_dir)
        if not path:
            results[name] = {"status": "MISSING", "path": None}
            continue
        results[name] = audit_srt(path)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(item["status"] == "ERROR" for item in results.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
