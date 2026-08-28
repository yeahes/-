import argparse
import json
import os
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRDataSeg
from app.core.llm_service_config import resolve_llm_service_config
from app.core.storage.cache_manager import CacheManager
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor, ScreenSubtitleItem

DEFAULT_MAX_ENGLISH_WORDS = 16


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest_max_english_words(run_manifest: dict) -> int:
    """Use the stable-cut contract when an older manifest lacks this field."""
    return int(run_manifest.get("max_english_words") or DEFAULT_MAX_ENGLISH_WORDS)


def _latest_artifact_dir() -> Path:
    candidates = sorted(
        (ROOT / "work-dir").glob("*/subtitle/*artifacts"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No stable artifact directory found under work-dir/*/subtitle/*artifacts")
    return candidates[0]


def _source_segments(transcript: list[dict]) -> list[ASRDataSeg]:
    return [
        ASRDataSeg(
            text=str(item.get("text") or ""),
            start_time=int(item.get("start_ms") or 0),
            end_time=int(item.get("end_ms") or 0),
            translated_text=str(item.get("translated_text") or ""),
        )
        for item in transcript
    ]


def _word_entries(word_ledger: dict) -> list[dict]:
    return [
        {
            "surface": item.get("surface") or item.get("normalized") or "",
            "token": item.get("normalized") or item.get("surface") or "",
            "start_time": int(item.get("start_ms") or 0),
            "end_time": int(item.get("end_ms") or 0),
        }
        for item in word_ledger.get("words", [])
    ]


def _groups_from_artifacts(semantic_groups: list[dict]) -> list[dict]:
    groups = []
    for group in semantic_groups:
        items = []
        for part in group.get("subtitle_parts", []):
            items.append(
                ScreenSubtitleItem(
                    source_ids=list(part.get("source_ids") or []),
                    original=str(part.get("original") or ""),
                    translated=str(part.get("translated") or ""),
                    word_start=part.get("word_start"),
                    word_end=part.get("word_end"),
                    subtitle_id=str(part.get("subtitle_id") or ""),
                )
            )
        groups.append(
            {
                "id": int(group.get("group_id") or group.get("id") or 0),
                "start_index": int(group.get("start_index") or 0),
                "items": items,
            }
        )
    return groups


def _items_from_spans(spans: list[dict]) -> list[ScreenSubtitleItem]:
    return [
        ScreenSubtitleItem(
            source_ids=list(item.get("source_ids") or []),
            original=str(item.get("original") or ""),
            translated=str(item.get("translated") or ""),
            word_start=item.get("word_start"),
            word_end=item.get("word_end"),
            subtitle_id=str(item.get("subtitle_id") or ""),
        )
        for item in spans
    ]


def _full_translations(allocation_inputs: list[dict]) -> dict[int, str]:
    return {
        int(item["id"]): str(item.get("full_translation") or "")
        for item in allocation_inputs
        if str(item.get("id", "")).isdigit()
    }


def _translation_map_from_segments(translations: list[dict]) -> dict[str, str]:
    return {
        str(item.get("subtitle_id") or f"S{index:04d}"): str(item.get("translated_text") or "")
        for index, item in enumerate(translations, 1)
    }


def _translation_map_from_items(items: list[ScreenSubtitleItem]) -> dict[str, str]:
    return {
        str(item.subtitle_id or f"S{index:04d}"): str(item.translated or "")
        for index, item in enumerate(items, 1)
    }


def _changed_translations(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    changed = []
    for subtitle_id in sorted(set(before) | set(after)):
        old = before.get(subtitle_id, "")
        new = after.get(subtitle_id, "")
        if old != new:
            changed.append({"subtitle_id": subtitle_id, "before": old, "after": new})
    return changed


def _resolve_llm_credentials(args) -> tuple[str, str, str]:
    base_url = (args.base_url or os.getenv("OPENAI_BASE_URL") or "").strip()
    api_key = (args.api_key or os.getenv("OPENAI_API_KEY") or "").strip()
    source = "args" if args.base_url or args.api_key else "env"
    if base_url and api_key:
        return base_url, api_key, source

    llm_runtime = resolve_llm_service_config()
    if llm_runtime.base_url and llm_runtime.api_key:
        source_name = llm_runtime.service.name.lower()
        return llm_runtime.base_url, llm_runtime.api_key, f"app_config.{source_name}"
    return base_url, api_key, source


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay only semantic allocation from frozen stable artifacts.")
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible API base URL. Defaults to env or app config.")
    parser.add_argument("--api-key", default=None, help="OpenAI-compatible API key. Defaults to env or app config.")
    parser.add_argument("--allocation-max-concurrency", type=int, default=2)
    parser.add_argument("--allocation-batch-size", type=int, default=16)
    parser.add_argument("--fresh-cache", action="store_true", help="Use an empty replay cache for allocation requests.")
    args = parser.parse_args()

    artifact_dir = args.artifact_dir or _latest_artifact_dir()
    run_manifest = _load_json(artifact_dir / "run-manifest.json")
    model = args.model or run_manifest.get("translation_model") or run_manifest.get("model") or "deepseek-v4-pro"
    output_dir = args.output_dir or artifact_dir.parent / f"allocation-only-replay-{ScreenSubtitleEditor._current_git_commit()[:8]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url, api_key, credential_source = _resolve_llm_credentials(args)
    if not (base_url and api_key):
        raise ValueError(
            "OPENAI_BASE_URL/OPENAI_API_KEY are missing and the selected app LLM config is empty"
        )
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_KEY"] = api_key

    allocation_inputs = _load_json(artifact_dir / "allocation-inputs.json")
    semantic_groups = _load_json(artifact_dir / "semantic-groups.json")
    subtitle_spans = _load_json(artifact_dir / "subtitle-spans.json")
    word_ledger = _load_json(artifact_dir / "word-ledger.json")
    transcript = _load_json(artifact_dir / "transcript.json")
    baseline_translations = _load_json(artifact_dir / "translations.json")

    editor = ScreenSubtitleEditor(
        model=model,
        max_cjk_chars=int(run_manifest.get("max_cjk_chars") or 24),
        max_english_words=_manifest_max_english_words(run_manifest),
        batch_num=24,
        timeout=90,
        enable_stable_mode=True,
        enable_quality_check=False,
        allocation_max_concurrency=args.allocation_max_concurrency,
        allocation_batch_size=args.allocation_batch_size,
    )
    if args.fresh_cache:
        cache_dir = output_dir / "allocation-cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        editor.cache_manager = CacheManager(str(cache_dir))

    editor._active_word_entries = _word_entries(word_ledger)
    editor._active_source_segments_by_id = {
        index: segment for index, segment in enumerate(_source_segments(transcript), 1)
    }
    editor._translation_structure_errors = []
    editor._last_llm_raw_returns = []
    editor._last_semantic_group_debug = []
    editor._last_allocation_inputs = []
    editor._last_allocation_raw_returns = []
    editor._last_allocation_validation = []
    editor._last_allocation_retry_log = []
    editor._last_allocation_final = []
    editor._last_allocation_unresolved = []
    editor._llm_cache_stats = {}
    editor._allocation_runtime_stats = {}

    groups = _groups_from_artifacts(semantic_groups)
    items = _items_from_spans(subtitle_spans)
    full_translations = _full_translations(allocation_inputs)
    source_segments = _source_segments(transcript)
    before = editor._allocation_isolation_snapshot(
        stage="before_allocation_replay",
        source_segments=source_segments,
        items=items,
        semantic_groups=groups,
        full_translations=full_translations,
    )
    allocated = editor._allocate_semantic_group_translations(groups, full_translations)
    applied = editor._apply_semantic_group_translations(items, groups, allocated)
    after = editor._allocation_isolation_snapshot(
        stage="after_allocation_replay",
        source_segments=source_segments,
        items=applied,
        semantic_groups=groups,
        full_translations=full_translations,
    )
    isolation_report = editor._build_allocation_isolation_report(before, after)

    baseline_map = _translation_map_from_segments(baseline_translations)
    replay_map = _translation_map_from_items(applied)
    changed = _changed_translations(baseline_map, replay_map)
    retry_accepted = [item for item in editor._last_allocation_retry_log if item.get("success")]
    retry_rejected = [item for item in editor._last_allocation_retry_log if item.get("attempted") and not item.get("success")]
    validation_failed = [item for item in editor._last_allocation_validation if item.get("issue_codes")]

    summary = {
        "artifact_dir": str(artifact_dir),
        "output_dir": str(output_dir),
        "model": model,
        "code_commit": ScreenSubtitleEditor._current_git_commit(),
        "fresh_cache": bool(args.fresh_cache),
        "allocation_max_concurrency": args.allocation_max_concurrency,
        "allocation_batch_size": args.allocation_batch_size,
        "llm_cache_stats": editor._llm_cache_stats,
        "allocation_runtime_stats": editor._allocation_runtime_stats,
        "credential_source": credential_source,
        "subtitle_count": len(items),
        "semantic_group_count": len(groups),
        "isolation_status": isolation_report.get("status"),
        "isolation_changed_keys": isolation_report.get("changed_keys", []),
        "validation_failed_record_count": len(validation_failed),
        "retry_attempt_count": len(editor._last_allocation_retry_log),
        "retry_accept_count": len(retry_accepted),
        "retry_reject_count": len(retry_rejected),
        "unresolved_count": len(editor._last_allocation_unresolved),
        "translation_changed_count": len(changed),
        "translation_structure_error_count": len(editor._translation_structure_errors),
    }

    _write_json(output_dir / "allocation-isolation-report.json", isolation_report)
    _write_json(output_dir / "allocation-inputs.json", editor._last_allocation_inputs)
    _write_json(output_dir / "allocation-raw-returns.json", editor._last_allocation_raw_returns)
    _write_json(output_dir / "allocation-validation.json", editor._last_allocation_validation)
    _write_json(output_dir / "allocation-retry-log.json", editor._last_allocation_retry_log)
    _write_json(output_dir / "allocation-final.json", editor._last_allocation_final)
    _write_json(output_dir / "allocation-unresolved.json", editor._last_allocation_unresolved)
    _write_json(output_dir / "translation-diff.json", changed)
    _write_json(output_dir / "replay-summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if isolation_report.get("status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
