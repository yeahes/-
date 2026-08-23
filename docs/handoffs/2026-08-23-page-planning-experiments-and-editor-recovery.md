# Page Planning Experiments And Editor Recovery

Verified: 2026-08-23 12:44:14 Asia/Shanghai

## Scope

This stage evaluated two production-independent long-caption strategies and
added a recoverable editor entry point. Neither experiment mutates stable
artifacts, subtitle caches, audio, the authoritative word ledger, or production
page selection.

## Experiment One: Fixed Parents, Alternate Pages

The experiment keeps parent English, fixed IDs, word ownership, and timing
unchanged. It selects only already-enumerated page candidates that produce a
material display improvement without a new page, font, timing, structural, or
unsupported-REVIEW regression.

Newest White House checkpoint:

- Content identity: `PASS`. Its stale semantic review queue is excluded from
  the page-content judgment.
- Offline replay baseline: 264 pages, 14 pages over 16 words.
- Candidate result: 263 pages, 13 pages over 16 words.
- Changed parents: `S0072`, `S0097`, `S0201`, and `S0205`.
- `S0097`, `S0201`, and `S0205` are clear viewing improvements.
- `S0072` is only a modest improvement and still contains a REVIEW page edge;
  it must remain visible to human review.
- All four changed bilingual page sets pass the current fixed-parent page
  contract. The experiment made one API request.

Cross-case guards produced zero page changes on historical White House 217,
Chocolate v27 230, Chocolate v29 221, and Employment 260.

Decision: keep this as a positive experimental candidate. Do not integrate it
into production until the user accepts the four actual bilingual page
sequences. Any integration must retain the same generic material-improvement
gate and historical guards.

Evidence:

- `scripts/experiment_fixed_parent_bilingual_pages.py`
- `output/fixed-parent-bilingual-page-ab-20260823.json`
- `output/fixed-parent-ab-historical-white-house.json`
- `output/fixed-parent-ab-chocolate-v27.json`
- `output/fixed-parent-ab-chocolate-v29.json`
- `output/fixed-parent-ab-employment.json`

## Experiment Two: Variable Parent Count

The experiment replaces one three-parent window with two or four provisional
parents. It preserves exact words, order, timestamps, speaker ownership, and
the real 56/54/52px page contract. Existing one-to-three-word neighboring
parents may remain unchanged, while every new or changed parent must pass the
production grammar and display gates.

Across the 14 requested targets, the final run examined 18,457 partitions and
found zero feasible candidates. `S0132` alone examined 61 partitions; 48 were
four-parent candidates, so its existing three-word and one-word neighbors no
longer prevented enumeration. The remaining candidates failed protected
syntax, subject/predicate, verb/object, fragment, timing, or actual page
planning contracts. No translation candidate existed, so the run made zero API
requests.

Decision: reject this bounded `3 -> 2/4` design. The result does not prove that
the underlying captions are impossible to improve; it proves that changing
parent count inside the tested three-parent window cannot do so without
breaking current frozen contracts.

Evidence:

- `scripts/audit_variable_parent_count_joint_planning.py`
- `output/variable-parent-count-joint-planning-20260823-final.json`

## Editor Recovery

The `More` menu now exposes `Restore Recent Subtitles`. It scans trusted stable
runs, editable failure checkpoints, and manual packages below the configured
work directory, deduplicates live aliases by attempt/run identity, and loads
the selected manifest directly into the editor. It does not start ASR,
translation, allocation, pagination, or any external request.

A normal application close now saves a manifest- and subtitle-hash-bound
working draft when the current editor state is dirty. Reopening a recent result
automatically restores that draft. Cancelling the result chooser leaves the
current session untouched. A draft write failure still requires an explicit
choice between remaining in the editor and exiting with possible loss.

Read-only acceptance against the real `work-dir` discovered and fully loaded
the newest five packages in 0.528 seconds. Focused verification passes:

- fixed-parent experiment: 2/2
- variable-parent experiment: 7/7
- manual editor: 120/120
- stable publication/UI: 93/93

The complete offline regression passes 30/30 in 902.68 seconds. `py_compile`
passes, and `git diff --check` reports only existing line-ending warnings. A
GUI-held `app.log` produced a harmless `WinError 32` rotation warning without
failing the run.

Implementation commits:

- `42a7b75` - offline bilingual page-planning experiments and tests
- `253d783` - recent-result editor recovery and recovery-draft tests
