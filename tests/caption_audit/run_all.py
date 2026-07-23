from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.caption_audit.metrics import audit_srt, pick_bilingual_original_top_srt
from tests.caption_audit.report import write_reports


DEFAULT_SAMPLES = ("000", "222", "888")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit stable bilingual subtitle outputs.")
    parser.add_argument(
        "samples",
        nargs="*",
        help="work-dir sample names. Defaults to CAPTION_AUDIT_SAMPLES or 000 222 888.",
    )
    parser.add_argument(
        "--work-dir",
        default=str(ROOT / "work-dir"),
        help="VideoCaptioner work-dir path.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "tests" / "caption_audit" / "out"),
        help="Report output directory.",
    )
    args = parser.parse_args(argv)

    samples = args.samples or _env_samples() or list(DEFAULT_SAMPLES)
    work_dir = Path(args.work_dir)
    results = {
        "status": "PASS",
        "work_dir": str(work_dir),
        "samples": {},
    }
    for name in samples:
        subtitle_dir = work_dir / name / "subtitle"
        path = pick_bilingual_original_top_srt(subtitle_dir)
        if not path:
            results["samples"][name] = {
                "status": "MISSING",
                "path": None,
                "count": 0,
                "errors": [],
                "warnings": [
                    {
                        "code": "missing_output",
                        "message": f"未找到 {name} 的稳定模式双语 SRT",
                    }
                ],
                "info": [],
            }
            continue
        results["samples"][name] = audit_srt(path)

    if any(sample["status"] == "ERROR" for sample in results["samples"].values()):
        results["status"] = "ERROR"
    elif any(sample["status"] in {"WARNING", "MISSING"} for sample in results["samples"].values()):
        results["status"] = "WARNING"

    json_path, md_path = write_reports(results, Path(args.out_dir))
    print(f"status={results['status']}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    return 1 if results["status"] == "ERROR" else 0


def _env_samples() -> list[str]:
    raw = os.environ.get("CAPTION_AUDIT_SAMPLES", "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
