# Structure Optimization Plan

Last updated: 2026-08-03

## Goal

Reduce implementation coupling without changing the stable subtitle contract.
This is a staged refactor, not a feature rewrite.

## Non-Negotiable Contracts

- English text, word-ledger order, word timestamps, subtitle boundaries, and
  global subtitle IDs freeze before Chinese allocation.
- LLMs may produce Chinese only. They cannot change English, IDs, order,
  timing, or the number of subtitle items.
- `ERROR` blocks synthesis; `WARNING` remains review evidence only.
- Existing stable artifact schemas remain readable by the application.
- Each stage must keep a focused regression test and pass
  `runtime\python.exe scripts\run_regression.py`.

## Staged Work

### 1. Allocation Candidate Acceptance

Extract the local decision that compares an existing fixed-ID Chinese
allocation with a retry, compression, or polish candidate.

- Keep request payloads, prompts, retry behavior, cache keys, and subtitle
  writeback in `ScreenSubtitleEditor`.
- Move only deterministic comparison policy and its small serializable result
  contract to `allocation_quality.py`.
- Keep the existing editor method as a compatibility adapter during migration.
- Add direct module tests for strict improvement, new high-confidence issue,
  natural adjacent Chinese order, and deterministic return values.

Progress: complete. The deterministic comparator is isolated in
`allocation_quality.py`; request orchestration and writeback remain in the
editor.

### 2. Stable Artifact Boundary

Extract stable artifact-path resolution and serialization from the editor.

- Keep artifact content and filenames unchanged.
- Make one writer own `subtitle-spans`, allocation artifacts, final timeline,
  validation, and manifest references.
- Do not make video synthesis search by fuzzy filename when a manifest exists.

Progress: artifact path resolution, single JSON writes, and the ordered stable
artifact write loop are now outside the editor. Payload construction stays in
the editor because it owns the active run state and artifact schema.

### 3. English Boundary Service Facade

Create a dedicated interface around finalized pre-ID English boundaries.

- The first step is a facade over existing tested local rules, not a wholesale
  move of every grammar heuristic.
- Inputs are source segments plus the frozen word ledger.
- Outputs are finalized items, boundary snapshots, and repair evidence.
- The interface must not depend on translation, allocation, rendering, or LLM
  state.

Progress: complete for the facade. `stable_english_boundaries.py` owns the
six-stage pre-ID order and snapshot handoff; grammar and repair rules remain
where their current regression coverage lives.

### 4. Test and Fixture Separation

Move new focused tests out of the monolithic stable-caption smoke file.

- Allocation quality tests become module tests.
- Boundary finalization and final timeline keep dedicated fixtures.
- Add compact frozen fixtures for known high-risk behaviors; avoid depending on
  mutable `work-dir` samples for pass/fail assertions.

Progress: the core local English boundary legality contract now has a compact
fixture. Broader end-to-end, renderer, and real-output smoke coverage remains
intentionally in place until its responsibilities are split further.

### 5. Legacy Path Isolation and Commit Hygiene

- Put compatibility-only code behind explicit helpers and document callers.
- Remove dead duplicate calls only after equivalent behavior is covered.
- Make small, reviewable commits by responsibility; never mix UI, timing,
  allocation, and English-cut changes in one commit.

Progress: the internal artifact-directory and JSON-writer wrappers had no
external callers and were removed after the shared writer tests covered their
behavior. Wider legacy path removal remains deferred until each caller has a
focused contract test.

## Deliberately Deferred

- No LLM English segmentation.
- No dynamic programming boundary system.
- No prompt/model/batch changes as part of structural extraction.
- No new subtitle rules until the responsible service has focused tests.
