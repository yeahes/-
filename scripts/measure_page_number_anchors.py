"""Measure Arabic-number ownership across bilingual display pages.

This is a read-only ROI probe for the page-semantic-anchor proposal.  It never
modifies a run directory and does not call a model or network service.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:%|％|st|nd|rd|th)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_ARTIFACT_SUFFIX = "-artifacts"


def _normalise_number(raw: str) -> str:
    value = str(raw or "").strip()
    percent = value.endswith(("%", "％"))
    if percent:
        value = value[:-1]
    value = re.sub(r"(?:st|nd|rd|th)$", "", value, flags=re.IGNORECASE)
    value = value.replace(",", "")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return ""
    normalised = format(number.normalize(), "f")
    if "." in normalised:
        normalised = normalised.rstrip("0").rstrip(".")
    if not normalised:
        normalised = "0"
    return f"{normalised}%" if percent else normalised


def extract_numbers(text: object) -> dict[str, list[str]]:
    """Return normalised number keys and their source spellings."""
    result: dict[str, list[str]] = {}
    for match in _NUMBER_RE.finditer(str(text or "")):
        raw = match.group(0)
        key = _normalise_number(raw)
        if not key:
            continue
        result.setdefault(key, []).append(raw)
    return result


def _page_text(page: Mapping[str, Any], field: str) -> str:
    if field == "zh":
        return str(page.get("zh") or page.get("chinese") or "")
    return str(page.get(field) or "")


def measure_parent(parent: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Measure one multipage parent and return only actionable observations."""
    parent_id = str(parent.get("parent_subtitle_id") or "")
    pages = [page for page in parent.get("pages") or [] if isinstance(page, Mapping)]
    if len(pages) <= 1:
        return []

    english_by_key: dict[str, set[str]] = {}
    chinese_by_key: dict[str, set[str]] = {}
    english_raw: dict[str, list[str]] = {}
    chinese_raw: dict[str, list[str]] = {}
    page_by_id: dict[str, Mapping[str, Any]] = {}
    for page in pages:
        page_id = str(page.get("display_page_id") or "")
        page_by_id[page_id] = page
        for key, spellings in extract_numbers(_page_text(page, "english")).items():
            english_by_key.setdefault(key, set()).add(page_id)
            english_raw.setdefault(key, []).extend(spellings)
        for key, spellings in extract_numbers(_page_text(page, "zh")).items():
            chinese_by_key.setdefault(key, set()).add(page_id)
            chinese_raw.setdefault(key, []).extend(spellings)

    observations: list[dict[str, Any]] = []
    for key in sorted(english_by_key):
        en_pages = sorted(english_by_key[key])
        zh_pages = sorted(chinese_by_key.get(key, set()))
        if len(en_pages) == 1 and len(zh_pages) == 1:
            bucket = "ok" if en_pages == zh_pages else "review"
        elif not zh_pages:
            bucket = "missing"
        else:
            bucket = "uncertain"
        if bucket == "ok":
            continue
        en_sample_page = page_by_id.get(en_pages[0]) if en_pages else None
        zh_sample_page = page_by_id.get(zh_pages[0]) if zh_pages else None
        if zh_sample_page is not None:
            sample_zh = _page_text(zh_sample_page, "zh")
        else:
            sample_zh = " | ".join(
                _page_text(page, "zh") for page in pages if _page_text(page, "zh")
            )
        observations.append(
            {
                "parent_id": parent_id,
                "number": key,
                "en_pages": en_pages,
                "zh_pages": zh_pages,
                "bucket": bucket,
                "sample_en": _page_text(en_sample_page or {}, "english"),
                "sample_zh": sample_zh,
                "english_spellings": sorted(set(english_raw.get(key, []))),
                "chinese_spellings": sorted(set(chinese_raw.get(key, []))),
            }
        )
    return observations


def _find_artifact(run_dir: Path, manifest: Mapping[str, Any]) -> Path:
    configured = str(manifest.get("display_page_translation_path") or "").strip()
    if configured and Path(configured).is_file():
        return Path(configured)
    candidates = sorted(
        path
        for path in run_dir.glob(f"*{_ARTIFACT_SUFFIX}/display-page-translations.json")
        if path.is_file()
    )
    if len(candidates) != 1:
        raise ValueError(
            f"expected one display-page-translations.json under {run_dir}, found {len(candidates)}"
        )
    return candidates[0]


def measure_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "stable-final-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"stable-final-manifest.json not found: {run_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    validation_status = str(manifest.get("validation_status") or "")
    page_status = str(manifest.get("display_page_translation_status") or "")
    if validation_status != "passed" or page_status != "PASS":
        return {
            "status": "REJECTED",
            "run_dir": str(run_dir),
            "reason": "selected run is not a PASS run",
            "validation_status": validation_status,
            "display_page_translation_status": page_status,
        }

    artifact_path = _find_artifact(run_dir, manifest)
    payload = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    parents = [
        parent
        for parent in payload.get("parents") or []
        if isinstance(parent, Mapping)
    ]
    multipage = [parent for parent in parents if len(parent.get("pages") or []) > 1]
    page_count = 0
    nonempty_page_count = 0
    observations: list[dict[str, Any]] = []
    for parent in multipage:
        pages = [page for page in parent.get("pages") or [] if isinstance(page, Mapping)]
        page_count += len(pages)
        nonempty_page_count += sum(bool(_page_text(page, "zh").strip()) for page in pages)
        observations.extend(measure_parent(parent))

    counts = {bucket: 0 for bucket in ("review", "missing", "uncertain")}
    for item in observations:
        counts[str(item["bucket"])] = counts.get(str(item["bucket"]), 0) + 1
    return {
        "status": "PASS",
        "run_dir": str(run_dir),
        "stable_run_id": str(manifest.get("stable_run_id") or run_dir.name),
        "validation_status": validation_status,
        "display_page_translation_status": page_status,
        "artifact_path": str(artifact_path),
        "multi_page_parents": len(multipage),
        "pages_checked": page_count,
        "page_chinese_nonempty": f"{nonempty_page_count}/{page_count}",
        "numbers_checked": sum(
            len({item["number"] for item in measure_parent(parent)})
            for parent in multipage
        ),
        "review_count": counts["review"],
        "missing_count": counts["missing"],
        "uncertain_count": counts["uncertain"],
        "items": observations,
    }


def run_synthetic_tests() -> None:
    wrong_page = {
        "parent_subtitle_id": "S9001",
        "pages": [
            {
                "display_page_id": "S9001.P01",
                "english": "Sales rose to 460%.",
                "zh": "销售增长。",
            },
            {
                "display_page_id": "S9001.P02",
                "english": "The increase continued.",
                "zh": "增长到了460%。",
            },
        ],
    }
    wrong = measure_parent(wrong_page)
    assert len(wrong) == 1 and wrong[0]["bucket"] == "review"
    assert wrong[0]["en_pages"] == ["S9001.P01"]
    assert wrong[0]["zh_pages"] == ["S9001.P02"]

    reordered_but_correct = {
        "parent_subtitle_id": "S9002",
        "pages": [
            {
                "display_page_id": "S9002.P01",
                "english": "In 2018, sales rose to 460%.",
                "zh": "销售在460%增长，发生在2018年。",
            },
            {
                "display_page_id": "S9002.P02",
                "english": "The project continued.",
                "zh": "项目继续。",
            },
        ],
    }
    assert measure_parent(reordered_but_correct) == []


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "run"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output",
        help="directory for measurement reports (never a run directory)",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        run_synthetic_tests()
        print("PASS synthetic number-anchor tests")
        return 0
    if not args.runs:
        parser.error("at least one PASS run directory is required")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports = [measure_run(path) for path in args.runs]
    for report in reports:
        run_id = _safe_name(str(report.get("stable_run_id") or Path(report["run_dir"]).name))
        target = args.output_dir / f"measure_page_number_anchors_{run_id}.json"
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({key: report.get(key) for key in (
            "stable_run_id", "status", "multi_page_parents", "numbers_checked",
            "review_count", "missing_count", "uncertain_count",
        )}, ensure_ascii=False))

    summary = {
        "status": "PASS" if all(report.get("status") == "PASS" for report in reports) else "REJECTED",
        "runs": reports,
    }
    summary_path = args.output_dir / "measure_page_number_anchors_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
