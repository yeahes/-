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

## Root-Cause-First Engineering Rule

- For every defect, first identify and correct the responsible data flow, state ownership,
  interface contract, or invariant. Do not treat a visible symptom as the implementation
  target when the underlying cause remains unresolved.
- Do not use sample-specific conditions, blacklist/allowlist growth, silent fallback,
  threshold relaxation, output-file patching, or repeated downstream repair as a substitute
  for a root-cause fix. A local exception is allowed only when the general invariant is
  already correct, the boundary condition is demonstrably isolated, and regression coverage
  proves it cannot affect unrelated inputs.
- Before adding a rule, state which invariant it enforces, which upstream owner is
  responsible, and why an earlier stage cannot enforce it. Prefer removing conflicting
  duplicate logic over adding another compensating layer.
- Every fix must add a regression test at the layer where the defect originated, and must
  preserve the project's frozen cross-stage contracts unless their explicit migration is
  part of the task.

## Root-Cause-First Timing Rule

- Treat a root-cause architectural fix as the first priority for every subtitle/audio
  timing defect. Do not use isolated cue padding, threshold relaxation, sample-specific
  exceptions, or downstream SRT/ASS patches as a substitute for repairing a conflicting
  timing data flow.
- There must be one authoritative final word ledger. Alignment backends may update that
  ledger's word times, but must not independently rewrite final cue times.
- Frozen cue spans map each global `subtitle_id` to its first and last word IDs. Final
  cue timings must be derived from those spans and must cover their own word envelope.
- Any final display-boundary reconciliation must preserve word-envelope coverage, frozen
  cue order, subtitle IDs, English text, and word timestamps. It must be validated before
  SRT/ASS export.
- Final SRT, ASS, and timing audit artifacts must be generated from the same ID-addressable
  cue timeline. Lost or synthetic IDs such as `S0000` are a validation failure, not
  acceptable diagnostic output.

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

## Verified Commit Discipline

- Do not commit every exploratory edit. Group one coherent change, run the
  proportionate focused tests and `git diff --check`, then create one checkpoint
  commit before using a real GUI/audio run to judge that change.
- A production result must be attributable to committed source. If source code
  is still modified, the manifest's `code_commit` identifies only `HEAD` and is
  not sufficient evidence for the exact implementation that produced the run.
- Never include `output/`, `work-dir/`, manual finals, caches, or other generated
  run artifacts in a source checkpoint commit unless the user explicitly asks
  to version a specific fixture.

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
