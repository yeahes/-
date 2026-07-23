# Project Instructions

## Project Purpose

This working copy optimizes VideoCaptioner for NotebookLM-style English podcast audio. The target output is a static educational video with stable bilingual subtitles: English on top, Simplified Chinese below.

## Hard Constraints

- Do not modify the original project under `D:\软件缓存\VideoCaptioner`.
- Only modify this working copy: `E:\VideoCaptioner-screen-subtitle`.
- Preserve the current successful video rendering path unless the task explicitly requires changing it.
- Prefer low-risk, incremental changes over broad rewrites.
- Do not let an LLM decide final English subtitle text, order, or timing in stable mode.
- Stable mode English segmentation must remain local, deterministic, and timestamp-based.
- Chinese translation may use an LLM, but it must map back to fixed English subtitle IDs.
- Do not silently change subtitle timing behavior. Document timing behavior changes in `docs/CURRENT_STATE.md`.

## Required Context Read Order

Before substantial edits, read:

1. `docs/PROJECT_OVERVIEW.md`
2. `docs/ARCHITECTURE.md`
3. `docs/PIPELINE.md`
4. `docs/SUBTITLE_RULES.md`
5. `docs/CURRENT_STATE.md`
6. The relevant task file under `tasks/active/`

## Required Workflow

Before editing:

1. Inspect relevant code before proposing or applying changes.
2. State the expected impact and regression risk.
3. Prefer adding or updating tests before changing fragile subtitle behavior.

After editing:

1. Run `runtime\python.exe scripts\run_regression.py`.
2. Review English coverage, order, length, timing gaps, and missing Chinese lines.
3. Check that generated stable subtitle outputs are the files used by synthesis.
4. Review the final diff.
5. Update `docs/CURRENT_STATE.md` when behavior changes.
6. Update the active task log if the change is part of a tracked task.

## Do Not

- Do not broadly rewrite `app/core/subtitle_processor/screen_editor.py` for a local issue.
- Do not replace stable timestamp-based segmentation with LLM segmentation.
- Do not re-enable candidate quality check inside stable mode unless there is a regression test proving it is safe.
- Do not delete spoken filler/backchannel text in stable mode. Prefer preserving or merging short display beats.
- Do not add dependencies unless necessary and explicitly reported.

## Documentation Routing

- Project purpose: `docs/PROJECT_OVERVIEW.md`
- Module map: `docs/ARCHITECTURE.md`
- Data flow and outputs: `docs/PIPELINE.md`
- Subtitle policy: `docs/SUBTITLE_RULES.md`
- Decisions and rejected approaches: `docs/DECISIONS.md`
- Current usable state and known risks: `docs/CURRENT_STATE.md`
- Regression commands: `docs/TESTING.md`
