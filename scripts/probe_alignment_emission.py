"""Small read-only probe for model-emitted Chinese-to-English word ranges.

The probe never writes to a run or checkpoint.  It asks an LLM for alignment
metadata only, validates that metadata locally, and projects the fixed parent
Chinese onto the already fixed English page ranges.
"""

from __future__ import annotations

import argparse
import json
import logging.handlers
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = [
    ROOT
    / "work-dir"
    / "中国人形机器人，赚钱仍是难题"
    / "subtitle"
    / "stable-runs"
    / "20260827T041727.676338-102dec4a",
    ROOT
    / "work-dir"
    / "拆解白宫所谓的中国转运骗局"
    / "subtitle"
    / "stable-runs"
    / "20260825T225507.737643-c92f6efe",
]
DEFAULT_DIAGNOSTIC_RUN = (
    ROOT
    / "work-dir"
    / "中国企业正把供应链铺满全球"
    / "subtitle"
    / "stable-checkpoints"
    / "20260827T072852.571821-69d9f215"
)
DEFAULT_GROUND_TRUTH = (
    Path("C:/Users/19379/Desktop")
    / "中国人形机器人，赚钱仍是难题"
    / "中国人形机器人，赚钱仍是难题-处理结果"
    / "人工终稿字幕包"
    / "generations"
    / "20260827T054046460067-b90f9792"
    / "人工终稿字幕-artifacts"
)
GROUND_TRUTH_IDS = ("S0100", "S0102", "S0104", "S0167", "S0176", "S0208")
DIAGNOSTIC_IDS = ("S0136", "S0260")
MIN_SAMPLE_PARENTS = 30
MAX_SAMPLE_PARENTS = 35
MAX_REQUESTS = 70
MAX_RETRIES = 1
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30


class _OfflineFileHandler(logging.FileHandler):
    def __init__(self, filename, mode="a", encoding=None, delay=False, errors=None, **_):
        super().__init__(filename, mode=mode, encoding=encoding, delay=delay, errors=errors)


# Loading the app config must not trigger a production-style app.log rollover.
logging.handlers.RotatingFileHandler = _OfflineFileHandler


SYSTEM_PROMPT = """You produce alignment metadata for a frozen bilingual subtitle.
The English words, subtitle ID, and Chinese parent text are authoritative.
Do not translate, rewrite, omit, or reorder any Chinese characters. Split the
given Chinese text into short contiguous phrases and map each phrase to the
0-based inclusive English word range that supports it.

Return one JSON object only:
{"phrases":[{"chinese":"...","word_start":0,"word_end":2}]}

Rules:
- Concatenating phrase.chinese values must reproduce parent_chinese exactly,
  character for character, including punctuation.
- Ranges are integers in 0..word_count-1, inclusive, and must be monotonic,
  non-overlapping, and within the parent.
- A phrase may cover more than one English word. Do not create English text or
  a second Chinese translation. If uncertain, still return the best alignment.
"""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _artifact_dir(run_dir: Path) -> Path:
    run_dir = run_dir.resolve()
    if (run_dir / "display-page-translations.json").is_file():
        return run_dir
    candidates = sorted(run_dir.glob("*-artifacts"))
    candidates = [path for path in candidates if (path / "display-page-translations.json").is_file()]
    if len(candidates) != 1:
        raise ValueError(f"expected one artifact directory under {run_dir}, found {len(candidates)}")
    return candidates[0]


def _manifest_status(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "stable-final-manifest.json"
    if not path.is_file():
        return {}
    manifest = _read_json(path)
    return {
        "validation_status": manifest.get("validation_status"),
        "display_page_translation_status": manifest.get("display_page_translation_status"),
        "stable_run_id": manifest.get("stable_run_id") or run_dir.name,
        "translation_model": manifest.get("display_page_translation_model")
        or manifest.get("translation_model"),
    }


def _page_records(payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for parent in payload.get("parents") or []:
        if not isinstance(parent, Mapping):
            continue
        parent_id = str(parent.get("parent_subtitle_id") or "")
        pages = [dict(page) for page in parent.get("pages") or [] if isinstance(page, Mapping)]
        if parent_id:
            result[parent_id] = pages
    return result


def _render_plan_records(payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for parent in payload.get("render_plans") or []:
        if not isinstance(parent, Mapping):
            continue
        parent_id = str(parent.get("parent_subtitle_id") or "")
        pages = [dict(page) for page in parent.get("pages") or [] if isinstance(page, Mapping)]
        if parent_id:
            result[parent_id] = pages
    return result


def load_rows(run_dir: Path, *, require_pass: bool = True, selected_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Load immutable parent/page evidence from one run or checkpoint."""
    run_dir = run_dir.resolve()
    status = _manifest_status(run_dir)
    if require_pass and (
        status.get("validation_status") != "passed"
        or status.get("display_page_translation_status") != "PASS"
    ):
        raise ValueError(f"selected run is not PASS: {run_dir} ({status})")
    artifacts = _artifact_dir(run_dir)
    authority = _read_json(artifacts / "authoritative-parent-chinese.json")
    pages_payload = _read_json(artifacts / "display-page-translations.json")
    ledger = _read_json(artifacts / "word-ledger.json")
    pages_by_parent = _page_records(pages_payload)
    render_pages_by_parent = _render_plan_records(pages_payload)
    words = ledger.get("words") or []
    wanted = {str(value) for value in selected_ids} if selected_ids else None
    rows: list[dict[str, Any]] = []
    for record in authority.get("records") or []:
        if not isinstance(record, Mapping):
            continue
        parent_id = str(record.get("subtitle_id") or "")
        if wanted is not None and parent_id not in wanted:
            continue
        pages = pages_by_parent.get(parent_id) or []
        if not pages:
            # ERROR checkpoints can still retain the deterministic English plan.
            pages = render_pages_by_parent.get(parent_id) or []
        if len(pages) <= 1:
            continue
        start = int(record.get("word_start"))
        end = int(record.get("word_end"))
        if start < 0 or end < start or end >= len(words):
            continue
        parent_words = [str(item.get("surface") or item.get("word") or "") for item in words[start : end + 1]]
        rows.append(
            {
                "run_dir": str(run_dir),
                "run_id": status.get("stable_run_id") or run_dir.name,
                "source_kind": "pass" if require_pass else "diagnostic",
                "parent_subtitle_id": parent_id,
                "english": str(record.get("english") or ""),
                "parent_chinese": str(record.get("chinese") or ""),
                "word_start": start,
                "word_end": end,
                "english_words": parent_words,
                "pages": sorted(pages, key=lambda page: (int(page.get("page_index") or 0), int(page.get("word_start") or 0))),
            }
        )
    return {"run_dir": str(run_dir), "status": status, "artifact_dir": str(artifacts), "rows": rows}


def select_sample(sources: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Select 30-35 PASS parents, keeping difficult robot IDs when available."""
    if not sources:
        raise ValueError("at least one PASS source is required")
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    missing_required: list[str] = []
    first_rows = sources[0]["rows"]
    first_by_id = {row["parent_subtitle_id"]: row for row in first_rows}
    for parent_id in GROUND_TRUTH_IDS:
        row = first_by_id.get(parent_id)
        if row is None:
            missing_required.append(parent_id)
            continue
        selected.append(row)
        seen.add((row["run_id"], row["parent_subtitle_id"]))

    quotas = [20, 10] + [MAX_SAMPLE_PARENTS] * max(0, len(sources) - 2)
    for source, quota in zip(sources, quotas):
        count = sum(1 for row in selected if row["run_id"] == source["status"].get("stable_run_id", ""))
        for row in source["rows"]:
            key = (row["run_id"], row["parent_subtitle_id"])
            if key in seen or count >= quota or len(selected) >= MAX_SAMPLE_PARENTS:
                continue
            selected.append(row)
            seen.add(key)
            count += 1
    if len(selected) < MIN_SAMPLE_PARENTS:
        raise ValueError(f"only {len(selected)} PASS multipage parents available for the probe")
    return selected, missing_required


def build_request(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "target_id": row["parent_subtitle_id"],
        "english": row["english"],
        "parent_chinese": row["parent_chinese"],
        "english_words": [
            {"index": index, "word": word}
            for index, word in enumerate(row["english_words"])
        ],
        "existing_pages": [
            {
                "display_page_id": str(page.get("display_page_id") or ""),
                "word_start": int(page.get("word_start") or 0) - int(row["word_start"]),
                "word_end": int(page.get("word_end") or 0) - int(row["word_start"]),
            }
            for page in row["pages"]
        ],
    }


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise ValueError("response is not a JSON object")
    return dict(payload)


def validate_emission(payload: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    phrases = payload.get("phrases")
    if phrases is None:
        phrases = payload.get("segments")
    if not isinstance(phrases, list) or not phrases:
        return {"ok": False, "failure_mode": "missing_phrases", "concat_ok": False}
    previous_end = -1
    pieces: list[str] = []
    normalized: list[dict[str, Any]] = []
    word_count = len(row["english_words"])
    for item in phrases:
        if not isinstance(item, Mapping):
            return {"ok": False, "failure_mode": "phrase_not_object", "concat_ok": False}
        chinese = str(item.get("chinese") or "")
        start = item.get("word_start")
        end = item.get("word_end")
        if isinstance(start, bool) or isinstance(end, bool):
            return {"ok": False, "failure_mode": "range_not_integer", "concat_ok": False}
        try:
            start = int(start)
            end = int(end)
        except (TypeError, ValueError):
            return {"ok": False, "failure_mode": "range_not_integer", "concat_ok": False}
        if not chinese:
            return {"ok": False, "failure_mode": "empty_chinese_phrase", "concat_ok": False}
        if start < 0 or end < start or end >= word_count:
            return {"ok": False, "failure_mode": "range_out_of_bounds", "concat_ok": False}
        if start <= previous_end:
            return {"ok": False, "failure_mode": "range_not_monotonic", "concat_ok": False}
        previous_end = end
        pieces.append(chinese)
        normalized.append({"chinese": chinese, "word_start": start, "word_end": end})
    concatenated = "".join(pieces)
    concat_ok = concatenated == str(row["parent_chinese"])
    if not concat_ok:
        return {
            "ok": False,
            "failure_mode": "chinese_concat_mismatch",
            "concat_ok": False,
            "concatenated": concatenated,
            "phrases": normalized,
        }
    return {"ok": True, "failure_mode": "", "concat_ok": True, "phrases": normalized}


def project_chinese_to_pages(row: Mapping[str, Any], validation: Mapping[str, Any]) -> dict[str, Any]:
    if not validation.get("ok"):
        raise ValueError("cannot project an invalid emission")
    pages = list(row["pages"])
    texts = ["" for _ in pages]
    cross_page_phrase_count = 0
    for phrase in validation["phrases"]:
        overlaps: list[tuple[int, int]] = []
        for index, page in enumerate(pages):
            start = int(page.get("word_start") or 0) - int(row["word_start"])
            end = int(page.get("word_end") or 0) - int(row["word_start"])
            overlap = max(0, min(end, phrase["word_end"]) - max(start, phrase["word_start"]) + 1)
            if overlap:
                overlaps.append((overlap, index))
        if not overlaps:
            raise ValueError("phrase does not intersect an existing page range")
        if len(overlaps) > 1:
            cross_page_phrase_count += 1
        _, page_index = max(overlaps, key=lambda item: (item[0], -item[1]))
        texts[page_index] += phrase["chinese"]
    return {
        "pages": [
            {
                "display_page_id": str(page.get("display_page_id") or ""),
                "chinese": texts[index],
            }
            for index, page in enumerate(pages)
        ],
        "cross_page_phrase_count": cross_page_phrase_count,
    }


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is None and isinstance(usage, Mapping):
            value = usage.get(key)
        if value is not None:
            result[key] = int(value)
    return result


def audit_rows(
    rows: Sequence[dict[str, Any]],
    completion: Callable[[dict[str, Any]], Any],
    *,
    max_retries: int = MAX_RETRIES,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    usage_total = Counter()
    raw_compliant = 0
    final_compliant = 0
    raw_concat = 0
    final_concat = 0
    retry_count = 0
    for row in rows:
        attempts: list[dict[str, Any]] = []
        first_validation: dict[str, Any] | None = None
        final_validation: dict[str, Any] | None = None
        projected: dict[str, Any] | None = None
        for attempt in range(max_retries + 1):
            try:
                response = completion(build_request(row))
                usage = None
                if isinstance(response, tuple) and len(response) == 2:
                    payload, usage = response
                else:
                    payload = response
                usage_total.update(_usage_dict(usage))
                payload = _parse_json_object(payload)
                validation = validate_emission(payload, row)
                attempts.append({"attempt": attempt + 1, "ok": validation.get("ok"), "failure_mode": validation.get("failure_mode", "")})
                if first_validation is None:
                    first_validation = validation
                final_validation = validation
                if validation.get("ok"):
                    projected = project_chinese_to_pages(row, validation)
                    break
            except Exception as exc:  # noqa: BLE001 - probe must classify provider failures.
                attempts.append({"attempt": attempt + 1, "ok": False, "failure_mode": "request_or_json_error", "error": str(exc)[:300]})
                if first_validation is None:
                    first_validation = {"ok": False, "failure_mode": "request_or_json_error", "concat_ok": False}
                final_validation = first_validation
            if attempt < max_retries:
                retry_count += 1
                time.sleep(0.05)
        if first_validation and first_validation.get("ok"):
            raw_compliant += 1
        if final_validation and final_validation.get("concat_ok"):
            final_concat += 1
        if first_validation and first_validation.get("concat_ok"):
            raw_concat += 1
        if final_validation and final_validation.get("ok"):
            final_compliant += 1
        results.append(
            {
                "parent_subtitle_id": row["parent_subtitle_id"],
                "run_id": row["run_id"],
                "source_kind": row["source_kind"],
                "attempts": attempts,
                "raw_compliant": bool(first_validation and first_validation.get("ok")),
                "compliant_after_retry": bool(final_validation and final_validation.get("ok")),
                "raw_concat_ok": bool(first_validation and first_validation.get("concat_ok")),
                "concat_ok_after_retry": bool(final_validation and final_validation.get("concat_ok")),
                "failure_mode": str((final_validation or {}).get("failure_mode") or ""),
                "phrases": (final_validation or {}).get("phrases") or [],
                "projected_pages": projected,
            }
        )
        if progress is not None:
            progress(results[-1])
    total = len(rows)
    failures = [item for item in results if not item["compliant_after_retry"]]
    return {
        "total": total,
        "raw_compliant_count": raw_compliant,
        "raw_compliance_rate": round(raw_compliant / total, 4) if total else 0.0,
        "compliant_after_retry_count": final_compliant,
        "compliance_rate_after_retry": round(final_compliant / total, 4) if total else 0.0,
        "raw_concat_equal_count": raw_concat,
        "raw_concat_equal_rate": round(raw_concat / total, 4) if total else 0.0,
        "concat_equal_after_retry_count": final_concat,
        "concat_equal_after_retry_rate": round(final_concat / total, 4) if total else 0.0,
        "retry_count": retry_count,
        "failures": failures,
        "failure_modes": dict(Counter(item["failure_mode"] for item in failures)),
        "token_usage": dict(usage_total),
        "results": results,
    }


def compare_ground_truth(rows: Sequence[dict[str, Any]], audit: Mapping[str, Any], truth_artifact: Path) -> dict[str, Any]:
    edits_path = truth_artifact.parent / "人工终稿字幕-edits.json"
    if edits_path.is_file():
        edits = _read_json(edits_path)
        truth: dict[str, list[str]] = {}
        for page in edits.get("display_page_edits") or []:
            if not isinstance(page, Mapping):
                continue
            parent_id = str(page.get("parent_subtitle_id") or "")
            if parent_id:
                truth.setdefault(parent_id, []).append(
                    str(page.get("chinese") or page.get("zh") or "")
                )
    else:
        payload = _read_json(truth_artifact / "display-page-translations.json")
        truth = {
            str(parent.get("parent_subtitle_id") or ""): [
                str(page.get("chinese") or page.get("zh") or "")
                for page in parent.get("pages") or []
                if isinstance(page, Mapping)
            ]
            for parent in payload.get("parents") or []
            if isinstance(parent, Mapping)
        }
    row_map = {row["parent_subtitle_id"]: row for row in rows}
    result_map = {item["parent_subtitle_id"]: item for item in audit.get("results") or []}
    details: list[dict[str, Any]] = []
    projected_hits = 0
    machine_hits = 0
    eligible = 0
    for parent_id in GROUND_TRUTH_IDS:
        row = row_map.get(parent_id)
        human_pages = truth.get(parent_id)
        if row is None or human_pages is None:
            details.append({"parent_subtitle_id": parent_id, "available": False, "reason": "not_in_selected_pass_sample_or_ground_truth"})
            continue
        eligible += 1
        machine_pages = [str(page.get("zh") or page.get("chinese") or "") for page in row["pages"]]
        result = result_map.get(parent_id) or {}
        projected_pages = [page["chinese"] for page in (result.get("projected_pages") or {}).get("pages") or []]
        projected_hit = projected_pages == human_pages
        machine_hit = machine_pages == human_pages
        projected_hits += int(projected_hit)
        machine_hits += int(machine_hit)
        details.append(
            {
                "parent_subtitle_id": parent_id,
                "available": True,
                "projected_page_count": len(projected_pages),
                "human_page_count": len(human_pages),
                "projected_hit": projected_hit,
                "machine_hit": machine_hit,
                "parent_chinese_equal": row["parent_chinese"] == "".join(human_pages),
            }
        )
    return {
        "requested_parent_count": len(GROUND_TRUTH_IDS),
        "eligible_parent_count": eligible,
        "projected_hit_count": projected_hits,
        "machine_hit_count": machine_hits,
        "details": details,
    }


def _live_completion(client: Any, model: str) -> Callable[[dict[str, Any]], Any]:
    def completion(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False, separators=(",", ":"))},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1024,
        )
        content = response.choices[0].message.content or ""
        return _parse_json_object(content), _usage_dict(getattr(response, "usage", None))

    return completion


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "run"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=Path, dest="runs")
    parser.add_argument("--provider", choices=("opencode", "deepseek"), default="opencode")
    parser.add_argument("--diagnostic-run", type=Path, default=DEFAULT_DIAGNOSTIC_RUN)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GROUND_TRUTH)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "f1-alignment-probe")
    parser.add_argument("--timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    run_paths = args.runs or DEFAULT_RUNS
    sources = [load_rows(path, require_pass=True) for path in run_paths]
    sample, missing_required = select_sample(sources)
    diagnostic_source = load_rows(args.diagnostic_run, require_pass=False, selected_ids=DIAGNOSTIC_IDS)
    diagnostic_rows = diagnostic_source["rows"]
    request_count = len(sample) + len(diagnostic_rows)
    if request_count > MAX_REQUESTS:
        raise RuntimeError(f"request budget exceeded: {request_count} > {MAX_REQUESTS}")

    from openai import OpenAI
    from app.common.config import cfg

    if args.provider == "deepseek":
        api_key = str(cfg.deepseek_api_key.value or "").strip()
        base_url = str(cfg.deepseek_api_base.value or "").strip()
        model = str(cfg.deepseek_model.value or "deepseek-v4-flash").strip()
        service_name = "DeepSeek"
    else:
        api_key = str(cfg.opencode_go_api_key.value or "").strip()
        base_url = str(cfg.opencode_go_api_base.value or "").strip()
        model = str(cfg.opencode_go_model.value or "deepseek-v4-flash").strip()
        service_name = "OpenCode Go"
    if not api_key:
        raise RuntimeError(f"{service_name} API key is not configured")
    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=args.timeout)
    completion = _live_completion(client, model)
    completed = 0

    def progress(item: dict[str, Any]) -> None:
        nonlocal completed
        completed += 1
        state = "PASS" if item.get("compliant_after_retry") else "FAIL"
        print(f"[{completed}/{request_count}] {item['run_id']} {item['parent_subtitle_id']} {state}", flush=True)

    sample_audit = audit_rows(sample, completion, progress=progress)
    diagnostic_audit = audit_rows(diagnostic_rows, completion, progress=progress) if diagnostic_rows else {"total": 0, "results": []}
    truth_artifact = args.ground_truth
    if not (truth_artifact / "display-page-translations.json").is_file():
        raise FileNotFoundError(f"ground-truth display-page-translations.json not found: {truth_artifact}")
    ground_truth = compare_ground_truth(sample, sample_audit, truth_artifact)
    report = {
        "probe": "F1-alignment-probe",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "service": service_name,
        "model": model,
        "base_url": base_url,
        "request_budget": {"used": request_count, "max": MAX_REQUESTS, "max_retries": MAX_RETRIES},
        "pass_sources": [{"run_dir": source["run_dir"], "status": source["status"], "multi_page_parent_count": len(source["rows"])} for source in sources],
        "sample": {
            "parent_count": len(sample),
            "run_count": len({row["run_id"] for row in sample}),
            "missing_required_robot_ids": missing_required,
            "ids": [row["parent_subtitle_id"] for row in sample],
            "audit": sample_audit,
        },
        "ground_truth": ground_truth,
        "diagnostic_supply_chain": {
            "run_dir": diagnostic_source["run_dir"],
            "status": diagnostic_source["status"],
            "requested_ids": list(DIAGNOSTIC_IDS),
            "available_ids": [row["parent_subtitle_id"] for row in diagnostic_rows],
            "audit": diagnostic_audit,
        },
        "failure_modes": dict(Counter(
            item.get("failure_mode") or "" for item in sample_audit.get("failures", []) + diagnostic_audit.get("failures", [])
        )),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / f"alignment-probe-{time.strftime('%Y%m%dT%H%M%S')}-{_safe_name(model)}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(target),
        "sample_parents": len(sample),
        "request_count": request_count,
        "raw_compliance_rate": sample_audit.get("raw_compliance_rate"),
        "compliance_rate_after_retry": sample_audit.get("compliance_rate_after_retry"),
        "raw_concat_equal_rate": sample_audit.get("raw_concat_equal_rate"),
        "concat_equal_after_retry_rate": sample_audit.get("concat_equal_after_retry_rate"),
        "ground_truth_projected_hits": ground_truth.get("projected_hit_count"),
        "ground_truth_machine_hits": ground_truth.get("machine_hit_count"),
        "S0136_S0260": diagnostic_audit,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
