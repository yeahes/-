# Architecture Map

## Main Pipeline

```text
audio input
-> ASR transcription
-> word-level timestamp data
-> stable local English segmentation
-> semantic grouping
-> LLM full Chinese translation
-> LLM Chinese allocation to fixed English parts
-> validation and report generation
-> stable subtitle outputs
-> video synthesis
```

## Important Modules

- `app/thread/transcript_thread.py`
  - Runs ASR and alignment workflows.
  - Handles FasterWhisper, Qwen3-ASR, and stable-ts integration paths.

- `app/thread/subtitle_thread.py`
  - Orchestrates subtitle split, translation, stable screen editing, validation, and subtitle file writing.
  - Stable mode should skip old LLM segmentation and candidate quality check.
  - Writes `stable-final-manifest.json` and stable final SRT files.

- `app/core/subtitle_processor/screen_editor.py`
  - Current main stable subtitle engine.
  - Performs local English cutting, semantic grouping, Chinese translation allocation, timing padding, validation, and artifact writing.
  - Uses frozen global subtitle IDs for Chinese allocation and final validation.
  - High regression risk. Avoid broad edits.

- `app/core/subtitle_processor/stable_pipeline_contracts.py`
  - Defines the serializable frozen-input contract shared by allocation and
  validation stages.
  - Hashes English source, word ledger, subtitle IDs/times, semantic groups,
  and authoritative full translations without depending on list positions.

- `app/core/subtitle_processor/stable_english_boundaries.py`
  - Owns the fixed pre-ID English boundary stage order and snapshot handoff.
  - Contains no grammar rules, LLM calls, translation/allocation state,
    rendering state, or subtitle-ID assignment.

- `app/core/subtitle_processor/stable_artifacts.py`
  - Owns stable artifact path resolution and ordered UTF-8 JSON serialization.
  - The editor still constructs payloads because it owns the active run state
    and must preserve existing artifact schemas.

- `app/core/subtitle_processor/allocation_quality.py`
  - Owns the deterministic acceptance decision for fixed-ID Chinese allocation
    candidates after local validation has produced comparable evidence.
  - Does not own prompts, cache access, retries, or subtitle-object writeback.

- `app/core/subtitle_processor/final_cue_timeline.py`
  - Owns the ID-addressable final cue timeline.
  - Derives every cue from its frozen `subtitle_id -> word_start/word_end`
    range and the final word ledger, then validates ID coverage, non-overlap,
    and own-word envelope coverage before export.

- Chinese candidate acceptance
  - Allocation retry and selective polish share one ID-bound candidate
    comparator. Retry requires a high-confidence issue to be fixed; polish
    requires a valid, non-regressive result because it is selected separately.
  - Speed compression and same-group reallocation use the same comparator
    before writeback. They must lower local reading pressure without adding a
    semantic, entity, number, negation, duplicate, or fragment regression;
    rejected candidates restore the original ID-bound Chinese fields.

- `app/thread/video_synthesis_thread.py`
  - Chooses subtitles for video synthesis.
  - Podcast template should prefer `stable-final-manifest.json`.

- `app/core/utils/podcast_learning_video.py`
  - Renders the educational static-video template.
  - Parses SRT and draws bilingual subtitle/video template frames.

- `tests/test_stable_caption_rules.py`
  - Unit/smoke coverage for segmentation, timing, coverage checks, and synthesis subtitle resolution.
  - Includes frozen-pipeline isolation checks for Chinese-only changes versus
    illegal English/ID/timing mutations.

- `tests/audit_stable_outputs.py`
  - Audits existing generated subtitles for timing gaps, short displays, overlong English, and missing Chinese.

## Change Routing

- Missing subtitles during speech:
  - Inspect ASR output, stable artifacts, coverage report, then final SRT/ASS.

- English line-break or overlong subtitle:
  - Inspect local stable cutting in `screen_editor.py`.
  - Do not solve this by giving segmentation control to the LLM.

- Chinese translation is unnatural:
  - Inspect semantic translation prompts and allocation.
  - Do not alter English segmentation for a Chinese-only problem.

- Chinese subtitle drifts against English after many lines:
  - Inspect `allocation-inputs.json`, `allocation-raw-returns.json`, `allocation-validation.json`, `translation-structure-errors.json`, then final SRT.
  - Verify every allocation response is keyed by global `subtitle_id`; do not diagnose this as a reading-speed problem first.

- Video output uses old subtitle:
  - Inspect `stable-final-manifest.json` and `resolve_podcast_template_subtitle`.

- Subtitle disappears too early:
  - Inspect `final-cue-timeline.json` first; the cue must contain its own
    first and final frozen ledger words.
  - Then inspect word-level alignment evidence for that exact word span.

## Coupling Warnings

- `screen_editor.py` currently mixes segmentation, translation, validation, timing, and artifact writing.
- Before any broad refactor, add tests around the exact behavior being preserved.
- Prefer extracting new helpers only when they reduce coupling and can be tested independently.
