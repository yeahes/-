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

## Blocking Triage

This section has priority over the Root-Cause-First rule below when a run is blocked.

- When a run is blocked, first report: the number of blocking points, whether the points can be bypassed in the manual final subtitle editor, the code-fix impact (how many pages and datasets it affects), and the verification cost in minutes.
- If the number of blocking points is small and they can be bypassed manually, the default recommendation is `manual bypass and publish`; register the code fix as a separate task and do not implement it in the same run.
- Recommend an immediate code fix only when the block is systemic: the same root cause recurs across datasets, or the blocking-point count within one dataset exceeds the agreed threshold.
- Every proposal to fix immediately must also provide the no-code workaround. The user chooses between the two options; do not prioritize on the user's behalf.
- Root-Cause-First governs how to fix a problem after the user decides to fix it; it does not require fixing every block immediately.

## Root-Cause-First Engineering And Timing Rule

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

1. `docs/ARCHITECTURE.md`
2. `docs/SUBTITLE_RULES.md`
3. `docs/CURRENT_STATE.md`

Additional context routing:

- Read `docs/PIPELINE.md` only when changing a cross-stage data flow.
- Read `docs/PROJECT_OVERVIEW.md` once when first taking over the repository.
- Read the newest round in `tasks/active/` and the current state summary under
  `tasks/active/`, which must remain at or below 50 lines.

## Required Workflow

Before editing:

1. Inspect relevant code before proposing or applying changes.
2. State the expected impact and regression risk.
3. Prefer adding or updating tests before changing fragile subtitle behavior.

After editing:

1. Follow the `Verification Tiering` section below; do not default to the full regression suite.
2. Review English coverage, order, length, timing gaps, and missing Chinese lines.
3. Check that generated stable subtitle outputs are the files used by synthesis.
4. Review the final diff.
5. Update `docs/CURRENT_STATE.md` when behavior changes.
6. Update the active task log if the change is part of a tracked task.

## Verification Tiering

- Default to focused verification: run only tests at the same layer as the change, then load existing artifacts and perform a local before/after page diff.
- `scripts/run_regression.py` defaults to `--profile full`; focused verification must explicitly use `--profile fast` or `--only <check-slug>`.
- Use `--profile full` only when one mechanism is being completed, a cross-stage contract or frozen data structure changed, or a checkpoint is being prepared for commit.
- During verification, do not invoke ASR or faster-whisper, download or load models, make network calls, or synthesize video unless the task itself changes that behavior.
- If focused verification takes more than one minute, stop and ask; do not expand it to the full suite automatically.
- Disable `app.log` rotation before running tests so `WinError 32` messages cannot bury the real assertion failure.

## Scope Discipline

- Do only the one named task. Record other problems found during the work in a final `发现但没动` list with file and line references instead of fixing them opportunistically.
- Do not change existing test assertions to make a change pass; add a new test for new behavior. Any deletion or modification of an existing `assert` must be listed separately with its reason and wait for user approval.
- In a given round, change only the named layer; do not alter adjacent layers such as page-selection logic.

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
