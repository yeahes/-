"""Bounded, read-only comparison of alignment request configurations.

This diagnostic never mutates a stable run or checkpoint. It sends at most
three requests for one frozen parent and records the provider response plus
the existing local hard-validator result.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.common.config import cfg
from app.core.llm_client import OpenAI as ProviderAwareOpenAI
from openai import OpenAI as RawOpenAI

from scripts.probe_alignment_emission import (
    DEFAULT_RUNS,
    SYSTEM_PROMPT,
    build_request,
    load_rows,
    validate_emission,
)


MAX_CALLS = 3
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 90.0


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise ValueError("response is not a JSON object")
    return dict(payload)


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


def _request_kwargs(variant: str) -> dict[str, Any]:
    if variant == "baseline":
        return {"max_tokens": 1024}
    if variant == "provider-aware":
        return {"max_completion_tokens": 8192}
    raise ValueError(f"unknown request variant: {variant}")


def _call_once(
    client: Any,
    model: str,
    row: Mapping[str, Any],
    variant: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        build_request(row),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
            **_request_kwargs(variant),
        )
        choice = response.choices[0]
        content = str(getattr(choice.message, "content", None) or "")
        payload = _parse_json_object(content)
        validation = (
            validate_emission(payload, row)
            if payload is not None
            else {"ok": False, "failure_mode": "empty_content", "concat_ok": False}
        )
        return {
            "ok": bool(validation.get("ok")),
            "failure_mode": str(validation.get("failure_mode") or ""),
            "concat_ok": bool(validation.get("concat_ok")),
            "finish_reason": str(getattr(choice, "finish_reason", "") or ""),
            "usage": _usage_dict(getattr(response, "usage", None)),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "content": content,
            "phrases": validation.get("phrases") or [],
        }
    except Exception as exc:  # noqa: BLE001 - classify diagnostic failures.
        return {
            "ok": False,
            "failure_mode": "request_or_json_error",
            "concat_ok": False,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "error": str(exc)[:500],
        }


def run_probe(
    row: Mapping[str, Any],
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float,
    variants: Sequence[str],
) -> dict[str, Any]:
    raw_client = RawOpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=timeout)
    provider_client = ProviderAwareOpenAI(
        base_url=base_url,
        api_key=api_key,
        max_retries=0,
        timeout=timeout,
    )
    clients = {"baseline": raw_client, "provider-aware": provider_client}
    results: list[dict[str, Any]] = []
    for variant in variants:
        result = _call_once(clients[variant], model, row, variant)
        result.update(
            {
                "variant": variant,
                "parent_subtitle_id": row["parent_subtitle_id"],
                "model": model,
            }
        )
        results.append(result)
    return {
        "probe": "F1-alignment-equivalence",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": base_url,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUNS[0])
    parser.add_argument("--parent-id", default="S0100")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--variant",
        action="append",
        choices=("baseline", "provider-aware"),
        dest="variants",
        help="Run one or more variants; default runs baseline then provider-aware.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/f1-alignment-probe/alignment-equivalence-latest.json"),
    )
    args = parser.parse_args(argv)
    variants = args.variants or ["baseline", "provider-aware", "provider-aware"]
    if len(variants) > MAX_CALLS:
        raise ValueError(f"request budget exceeded: {len(variants)} > {MAX_CALLS}")

    source = load_rows(args.run, require_pass=True, selected_ids=[args.parent_id])
    rows = source["rows"]
    if len(rows) != 1:
        raise ValueError(f"expected one multipage parent, found {len(rows)}: {args.parent_id}")
    api_key = str(cfg.deepseek_api_key.value or "").strip()
    base_url = str(cfg.deepseek_api_base.value or "").strip()
    if not api_key or not base_url:
        raise RuntimeError("DeepSeek API is not configured")

    report = run_probe(
        rows[0],
        model=args.model,
        base_url=base_url,
        api_key=api_key,
        timeout=args.timeout,
        variants=variants,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
