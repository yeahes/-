"""Read-only OpenCode audit for fixed-ID bilingual subtitle artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI

from app.common.config import cfg
from app.core.subtitle_processor.translation_quality_audit import (
    audit_fixed_id_translation_quality,
)


ISSUE_CODES = {
    "semantic_loss",
    "meaning_error",
    "number_or_negation_error",
    "english_chinese_mismatch",
    "adjacent_coherence",
    "translationese",
    "chinese_too_long",
    "asr_suspicious",
    "asr_format_error",
}


SYSTEM_PROMPT = """You audit Simplified Chinese subtitles for an English podcast.
The English text and subtitle IDs are frozen and must never be rewritten.
Report only clear, high-value problems that a human should fix before synthesis:
semantic loss, wrong meaning, lost number/negation, English-Chinese mismatch,
broken continuity with adjacent subtitles, stiff translationese, excessive
Chinese reading load, or an obvious English ASR error such as a nonsensical
phrase, malformed proper name, split number suffix, or broken compound. Do not
report merely awkward spoken grammar, acceptable paraphrases, or punctuation.

Return one JSON object only:
{"issues":[{"subtitle_ids":["S0001"],"code":"semantic_loss",
"reason":"short Chinese explanation","confidence":"high"}]}
Allowed codes: semantic_loss, meaning_error, number_or_negation_error,
english_chinese_mismatch, adjacent_coherence, translationese, chinese_too_long.
Also allowed: asr_suspicious, asr_format_error.
Use only IDs present in the input. Use one or two adjacent IDs per issue.
If no clear problem exists, return {"issues":[]}.
"""


def _load_rows(artifact_dir: Path) -> list[dict[str, Any]]:
    payload = json.loads(
        (artifact_dir / "authoritative-parent-chinese.json").read_text(
            encoding="utf-8-sig"
        )
    )
    page_payload = json.loads(
        (artifact_dir / "display-page-translations.json").read_text(
            encoding="utf-8-sig"
        )
    )
    pages_by_parent = {
        str(parent.get("parent_subtitle_id") or ""): [
            {
                "display_page_id": str(page.get("display_page_id") or ""),
                "english": str(page.get("english") or ""),
                "chinese": str(page.get("zh") or ""),
                "duration_ms": max(
                    1,
                    int(page.get("end_ms") or 0)
                    - int(page.get("start_ms") or 0),
                ),
            }
            for page in parent.get("pages") or []
            if isinstance(page, dict)
        ]
        for parent in page_payload.get("parents") or []
        if isinstance(parent, dict)
    }
    rows = []
    for record in payload.get("records") or []:
        subtitle_id = str(record.get("subtitle_id") or "")
        if not re.fullmatch(r"S\d{4}", subtitle_id):
            continue
        rows.append(
            {
                "subtitle_id": subtitle_id,
                "english": str(record.get("english") or ""),
                "chinese": str(record.get("chinese") or ""),
                "pages": pages_by_parent.get(subtitle_id, []),
            }
        )
    return rows


def _parse_json_object(text: str) -> dict:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("audit response must be a JSON object")
    return payload


def _validated_issues(payload: dict, known_ids: set[str]) -> list[dict]:
    result = []
    seen = set()
    for item in payload.get("issues") or []:
        if not isinstance(item, dict):
            continue
        subtitle_ids = sorted(
            {
                str(value)
                for value in item.get("subtitle_ids") or []
                if str(value) in known_ids
            }
        )
        code = str(item.get("code") or "")
        confidence = str(item.get("confidence") or "").lower()
        reason = str(item.get("reason") or "").strip()[:500]
        key = (tuple(subtitle_ids), code, reason)
        if (
            not subtitle_ids
            or len(subtitle_ids) > 2
            or code not in ISSUE_CODES
            or confidence != "high"
            or not reason
            or key in seen
        ):
            continue
        seen.add(key)
        result.append(
            {
                "subtitle_ids": subtitle_ids,
                "code": code,
                "reason": reason,
                "confidence": confidence,
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()
    rows = _load_rows(args.artifact_dir)
    if not rows:
        raise RuntimeError("artifact has no fixed-ID parent Chinese records")

    api_key = str(cfg.opencode_go_api_key.value or "").strip()
    if not api_key:
        raise RuntimeError("OpenCode Go API key is not configured")
    base_url = str(cfg.opencode_go_api_base.value or "").strip()
    model = str(cfg.opencode_go_model.value or "deepseek-v4-flash").strip()
    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=1, timeout=180)
    def completion(request: dict) -> dict:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": request["system_prompt"]},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "target_ids": request["target_ids"],
                            "subtitles": request["rows"],
                            **(
                                {"candidate_issues": request["candidate_issues"]}
                                if request.get("candidate_issues")
                                else {}
                            ),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return _parse_json_object(response.choices[0].message.content or "")

    result = audit_fixed_id_translation_quality(
        rows,
        completion,
        model=model,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
