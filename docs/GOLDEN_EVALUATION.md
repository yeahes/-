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

Schema v1 keeps the original full-transcript checks:

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

## Schema v2: production quality gates

Schema v2 evaluates the current stable pipeline in four independently scored
components:

- English segmentation: 25%.
- Parent Chinese translation: 35%.
- Fixed-ID Chinese allocation: 15%.
- Actual display pages: 25%.

The default acceptance threshold is 90% overall and 85% for every component.
A high overall score cannot hide a weak component or a failed hard contract.

English anchors replace fixed `Sxxxx` references so a valid re-segmentation
can still be evaluated. An anchor must be unique. Use `anchor_occurrence` only
when the same phrase genuinely appears more than once.

```json
{
  "schema_version": 2,
  "sample_id": "human-reviewed-sample",
  "english_segmentation": {
    "windows": [
      {
        "anchor_id": "reason-boundary",
        "english_anchor": "They raised the price specifically because demand increased.",
        "expected_segments": [
          "They raised the price",
          "specifically because demand increased."
        ]
      }
    ]
  },
  "parent_translation": {
    "anchors": [
      {
        "anchor_id": "price-fact",
        "english_anchor": "They raised the price",
        "must_contain_any": [["提价", "提高价格"]],
        "accepted_chinese": ["他们提高了价格。"],
        "max_chinese_chars": 12
      }
    ]
  },
  "fixed_id_allocation": {
    "anchors": [
      {
        "anchor_id": "demand-owner",
        "english_anchor": "demand increased",
        "must_contain_any": [["需求"], ["增长", "上升"]],
        "must_not_appear_in_adjacent": true
      }
    ]
  },
  "display_pages": {
    "windows": [
      {
        "anchor_id": "reason-pages",
        "english_anchor": "They raised the price specifically because demand increased.",
        "expected_segments": [
          "They raised the price",
          "specifically because demand increased."
        ],
        "max_words_per_page": 9,
        "min_english_font_size": 52,
        "max_english_lines": 2
      }
    ]
  },
  "thresholds": {
    "min_overall_score": 0.9,
    "min_component_score": 0.85
  }
}
```

The v2 hard gate checks word-ledger coverage, stable IDs and ranges, final cue
timeline validity, parent-Chinese authority, validation and English-boundary
reports, display-page coverage, and display-page authority/contract hashes.
Modern schema-v2 runs must contain all evidence. A legacy package that predates
the validation and boundary reports may be evaluated through its ID-bound final
timeline; missing newer files are reported under `compatibility.notes`, not
silently treated as modern evidence.

Curated references live under `tests/fixtures/golden_subtitles/`. The offline
regression loads both `dreamcore-v2.json` and `bad-animation-v2.json`. The
reference files contain only human-selected windows; they do not copy full
production artifacts and never trigger an API request.
