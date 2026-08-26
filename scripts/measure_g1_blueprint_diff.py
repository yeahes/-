"""Offline replay and diff for the frozen female-set display-page blueprint."""

from __future__ import annotations

import argparse
import json
import logging.handlers
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT = (
    ROOT
    / "work-dir"
    / "中国职场女性为何悄然掉队？"
    / "subtitle"
    / "stable-checkpoints"
    / "20260826T040659.244182-79951e43"
)


class _OfflineFileHandler(logging.FileHandler):
    def __init__(self, filename, mode="a", encoding=None, delay=False, errors=None, **_):
        super().__init__(filename, mode=mode, encoding=encoding, delay=delay, errors=errors)


# This script is a local read-only measurement. Prevent importing the app logger
# from attempting a production-style rollover while loading the planner.
logging.handlers.RotatingFileHandler = _OfflineFileHandler

from app.core.utils.podcast_learning_video import Cue  # noqa: E402
from app.core.utils.podcast_learning_video import (  # noqa: E402
    build_article_display_page_blueprint,
)


ARTIFACT_DIR_NAME = (
    "【样式字幕】中国职场女性为何悄然掉队？-FasterWhisper ✨-英语-LLM 大模型翻译-artifacts"
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_dir(checkpoint: Path) -> Path:
    candidates = [checkpoint / ARTIFACT_DIR_NAME]
    candidates.extend(path for path in checkpoint.iterdir() if path.is_dir())
    for candidate in candidates:
        if (candidate / "display-page-translations.json").exists():
            return candidate
    raise FileNotFoundError("display-page-translations.json not found under checkpoint")


def _build_cues(artifacts: Path) -> list[Cue]:
    ledger = _read_json(artifacts / "word-ledger.json")
    timeline = _read_json(artifacts / "final-cue-timeline.json")
    authoritative = _read_json(artifacts / "authoritative-parent-chinese.json")
    evidence = _read_json(artifacts / "display-boundary-evidence.json").get("boundaries") or {}
    words = ledger["words"]
    timeline_by_id = {str(item["subtitle_id"]): item for item in timeline["records"]}
    cues: list[Cue] = []
    for record in authoritative["records"]:
        subtitle_id = str(record["subtitle_id"])
        timeline_record = timeline_by_id[subtitle_id]
        start = int(record["word_start"])
        end = int(record["word_end"])
        word_timing = tuple(
            {
                "word_id": int(word["word_id"]),
                "surface": str(word["surface"]),
                "start": float(word["start_ms"]) / 1000.0,
                "end": float(word["end_ms"]) / 1000.0,
            }
            for word in words[start : end + 1]
        )
        cues.append(
            Cue(
                index=int(re.sub(r"^S", "", subtitle_id)),
                start=float(timeline_record["start_ms"]) / 1000.0,
                end=float(timeline_record["end_ms"]) / 1000.0,
                en=str(record["english"]),
                zh=str(record["chinese"]),
                speaker="",
                subtitle_id=subtitle_id,
                word_timing=word_timing,
                display_boundary_evidence=evidence,
            )
        )
    return cues


def _page_key(parent_id: str, page: dict[str, Any]) -> tuple[str, str]:
    return parent_id, str(page.get("display_page_id") or "")


def _page_signature(page: dict[str, Any]) -> str:
    return json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _page_map(artifact: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for plan in artifact.get("render_plans") or []:
        parent_id = str(plan.get("parent_subtitle_id") or "")
        for page in plan.get("pages") or []:
            result[_page_key(parent_id, page)] = dict(page)
    return result


def _g7_page_keys(page_map: dict[tuple[str, str], dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        key
        for key, page in page_map.items()
        if bool((page.get("boundary_before") or {}).get("relative_clause_has_trailing_predicate"))
    }


def measure(checkpoint: Path) -> dict[str, Any]:
    artifacts = _artifact_dir(checkpoint)
    original = _read_json(artifacts / "display-page-translations.json")
    cues = _build_cues(artifacts)
    try:
        replayed = build_article_display_page_blueprint(cues)
    except Exception as exc:  # RenderStructuralOverflowError carries the read-only partial artifact.
        replayed = getattr(exc, "partial_blueprint", None)
        if not isinstance(replayed, dict):
            raise
        replayed = dict(replayed)
        replayed.setdefault("replay_exception", type(exc).__name__)

    old_pages = _page_map(original)
    new_pages = _page_map(replayed)
    page_keys = set(old_pages) | set(new_pages)
    changed_keys = {
        key
        for key in page_keys
        if _page_signature(old_pages.get(key, {}))
        != _page_signature(new_pages.get(key, {}))
    }
    g7_keys = _g7_page_keys(old_pages) | _g7_page_keys(new_pages)
    g1_keys = {
        key
        for key in changed_keys
        if key[0] == "S0089"
        or bool(old_pages.get(key, {}).get("degraded"))
        or bool(new_pages.get(key, {}).get("degraded"))
    }
    s0089 = next(
        plan for plan in replayed.get("render_plans") or []
        if str(plan.get("parent_subtitle_id") or "") == "S0089"
    )
    return {
        "checkpoint": str(checkpoint),
        "status": replayed.get("status"),
        "errors_count": len(replayed.get("errors") or []),
        "degraded_page_count": replayed.get("degraded_page_count", 0),
        "degraded_parents": replayed.get("degraded_parents") or [],
        "s0089": {
            "renderable": s0089.get("renderable"),
            "degraded": s0089.get("degraded"),
            "english_font_size": s0089.get("english_font_size"),
            "page_font_sizes": [
                page.get("english_font_size") for page in s0089.get("pages") or []
            ],
        },
        "total_pages": len(new_pages),
        "changed_pages": len(changed_keys),
        "g1_pages": len(g1_keys),
        "g7_pages": len(changed_keys & g7_keys),
        "g7_changed_page_ids": sorted(
            f"{parent}.{page_id}" for parent, page_id in changed_keys & g7_keys
        ),
        "page_artifact_status_pass": replayed.get("status") == "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    options = parser.parse_args()
    print(json.dumps(measure(options.checkpoint), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
