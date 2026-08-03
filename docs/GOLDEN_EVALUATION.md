# Golden Subtitle Evaluation

`scripts/evaluate_golden_subtitles.py` evaluates a completed stable subtitle
artifact directory against manually curated reference data. It is offline and
read-only: it never calls an LLM and cannot alter a completed run.

Run it with:

```powershell
runtime\python.exe scripts\evaluate_golden_subtitles.py `
  --reference <golden-reference.json> `
  --run work-dir\sample\subtitle\sample-artifacts `
  --output work-dir\sample\subtitle\golden-evaluation.json
```

The reference JSON uses this schema:

```json
{
  "schema_version": 1,
  "sample_id": "human-readable-sample-id",
  "english_text": "Manually verified full English transcript.",
  "entities": [
    {"canonical_name": "Pop Mart", "category": "brand"}
  ],
  "boundaries_after_word_index": [11, 24],
  "word_timings": [
    {"word_id": 0, "start_ms": 120, "end_ms": 260}
  ],
  "chinese_anchors": [
    {
      "anchor_id": "brand-and-number",
      "subtitle_ids": ["S0042", "S0043"],
      "must_contain_any": [["泡泡玛特"], ["36%", "百分之三十六"]],
      "must_not_contain": ["美元"]
    }
  ],
  "thresholds": {
    "max_word_error_rate": 0.03,
    "min_recall": 0.95,
    "min_f1": 0.90,
    "max_mean_absolute_error_ms": 100,
    "max_p90_absolute_error_ms": 250
  }
}
```

`must_contain_any` is an AND of groups and an OR inside each group. It is
suited to a manually confirmed entity, number, currency, negation, or other
critical fact. It does not claim to measure general Chinese fluency.

Add a sample only after a human has checked its reference transcript, timing,
boundaries, and fact anchors. Do not derive a golden reference from the same
output being evaluated.
