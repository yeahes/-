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
  - High regression risk. Avoid broad edits.

- `app/thread/video_synthesis_thread.py`
  - Chooses subtitles for video synthesis.
  - Podcast template should prefer `stable-final-manifest.json`.

- `app/core/utils/podcast_learning_video.py`
  - Renders the educational static-video template.
  - Parses SRT and draws bilingual subtitle/video template frames.

- `tests/test_stable_caption_rules.py`
  - Unit/smoke coverage for segmentation, timing, coverage checks, and synthesis subtitle resolution.

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

- Video output uses old subtitle:
  - Inspect `stable-final-manifest.json` and `resolve_podcast_template_subtitle`.

- Subtitle disappears too early:
  - Inspect final stable SRT/ASS timing first.
  - Then inspect word-level timestamp gaps.

## Coupling Warnings

- `screen_editor.py` currently mixes segmentation, translation, validation, timing, and artifact writing.
- Before any broad refactor, add tests around the exact behavior being preserved.
- Prefer extracting new helpers only when they reduce coupling and can be tested independently.
