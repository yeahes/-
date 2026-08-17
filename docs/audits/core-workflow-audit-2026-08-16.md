# Core Workflow Audit - 2026-08-16

## Scope

- Audited commit: `55974cc99542d36559ad2f063247f1997cf1497d` on `main`.
- Scope: ASR handoff, stable English segmentation, fixed-ID Chinese translation,
  display pagination, final timing, manual editing, publication, synthesis,
  caching, failure recovery, and regression coverage.
- This audit did not change business code, call a paid model, or write production
  artifacts.
- Evidence included code and tests at HEAD, one oil-production package, and one
  saved manual-final package. Historical artifacts were used as behavioral
  evidence only when their producing commit was known.

## Overall Result

No P0 data-loss or arbitrary-file-write defect was found. The stable pipeline's
main ownership model is sound: English, fixed IDs, word spans, and final timing
are protected from LLM writeback, failed stable runs do not replace the published
root manifest, and manual-final publication is generation-based and hash-bound.

The remaining problems are not one undifferentiated subtitle issue. They fall
into four independent groups:

1. Renderer and synthesis entry points do not enforce every upstream authority
   contract.
2. Page-level Chinese and visual page boundaries can be formally publishable
   while still being visibly awkward.
3. Quality detectors, editor marks, automatic retries, and release audits do not
   share one definition of an actionable issue.
4. Most production time is external translation latency, while some manual edit
   latency is still caused by whole-table work on the GUI thread.

## P1 Findings

### P1-1 Renderer does not validate the authoritative parent-Chinese binding

- Evidence:
  - `app/core/utils/podcast_learning_video.py:6459` loads and hashes the
    display-page artifact.
  - `app/core/utils/podcast_learning_video.py:6350` applies it by comparing only
    `source_parent_chinese` with the current cue Chinese.
  - `app/core/subtitle_processor/authoritative_parent_chinese.py:306` provides
    the stronger `validate_display_page_parent_records()` contract, but the
    renderer does not call it.
- Impact: a hash-valid page artifact can still refer to a stale or wrong parent
  authority record. `parent_record_hash` is written but not consumed at render.
- Owner: renderer preflight, not the translation model.
- Fix: resolve and hash-check `parent_chinese_authority_path`, validate the
  authority against the current fixed-ID cues, then validate every page parent
  record before attaching page translations.
- Risk/effort: low-to-medium; add fail-closed renderer tests for missing, stale,
  and mismatched authority records.

### P1-2 Renderer duplicates only part of the final-timeline validator

- Evidence:
  - `app/core/utils/podcast_learning_video.py:726` manually checks timeline,
    ledger, SRT order, text, and ranges.
  - `app/core/subtitle_processor/final_cue_timeline.py:241` is the authoritative
    complete validator.
  - Production checks `validation.status == PASS` in
    `app/thread/subtitle_thread.py:452`, but independent rendering does not.
- Impact: a replay or manually assembled package can be accepted by a weaker
  validation path; future timeline rules can drift between the two copies.
- Fix: invoke the canonical final-timeline validator at render load, then keep
  the SRT comparison only as an extra projection check.
- Risk/effort: low.

### P1-3 A new pipeline task can replace unsaved manual edits without confirmation

- Evidence:
  - `app/view/subtitle_interface.py:2219` `set_task()` stops the old thread and
    replaces the task immediately.
  - `update_info()` resets the table and `_load_manual_final_session()` clears
    the old session.
  - File import correctly calls `_confirm_discard_manual_edits()` at
    `app/view/subtitle_interface.py:2518`, so the two entry paths disagree.
- Impact: starting another Home workflow can discard edits made before the
  recovery draft has been persisted.
- Fix: use the same discard/save guard before any task or session replacement;
  rejection must leave the old task, thread, table, and session untouched.
- Risk/effort: low; requires an interaction regression test.

### P1-4 A stable manifest can enter the non-podcast synthesis path

- Evidence:
  - `open_manual_final_in_synthesis()` sends the manifest at
    `app/view/subtitle_interface.py:3719`.
  - `resolve_synthesis_package_inputs()` validates it but deliberately returns
    the manifest path at `app/thread/video_synthesis_thread.py:216`.
  - Only the podcast-template branch resolves the manifest to the owned SRT at
    `app/thread/video_synthesis_thread.py:533`; with that template disabled,
    line 569 sends JSON to `add_subtitles()`.
- Impact: the editor-to-synthesis handoff can look valid and then fail at render
  with an unrelated subtitle parse error.
- Fix: a stable/manual package must force and lock the article podcast template,
  or the thread must reject JSON manifests outside that path. Keep the backend
  rejection even after the UI is corrected.
- Risk/effort: low.

### P1-5 Article-analysis cache identity omits the prompt policy

- Evidence:
  - `app/core/article_context.py:171` keys the request by article text only.
  - Cache parameters include model, task, and schema version, but not
    `ARTICLE_CONTEXT_PROMPT`, a prompt hash, or a prompt-policy version.
  - `_analysis_meta.prompt_hash` currently stores the article-text hash, not the
    prompt hash.
- Impact: improving name, term, or entity extraction can still return an older
  cached article analysis for the same article and model. This directly affects
  proper-noun correction and terminology consistency after code upgrades.
- Fix: add an explicit article-analysis prompt version and prompt hash to both
  the LLM cache identity and durable run fingerprint; record them accurately in
  metadata.
- Risk/effort: low. Old cache rows can remain; the new identity naturally stops
  reading them.

### P1-6 Page-level Chinese has no expansion or repetition contract

- Evidence:
  - The prompt asks for concise page Chinese at
    `app/core/subtitle_processor/screen_editor.py:404`.
  - `app/core/subtitle_processor/stable_display_page_contract.py:405` checks
    per-page reading capacity, IDs, source echoes, and basic shape, but not the
    aggregate expansion relative to the authoritative parent or repeated facts
    across pages.
  - Current renderer QA at `app/core/subtitle_processor/screen_editor.py:1780`
    also omits those checks.
- Real-package evidence:
  - `S0117`: parent Chinese is 28 CJK characters; page Chinese expands to 40 and
    repeats the disappearance claim.
  - `S0136`: parent Chinese is 28; page Chinese expands to 42.
  - `S0122`: page Chinese reintroduces the filler `还有变化`.
- Impact: the Pro parent translation can be concise while the actual rendered
  pages become longer, repetitive, or less natural.
- Fix: validate aggregate length ratio, novel-content anchors, and adjacent-page
  repetition per parent. Retry only failed parents; if still unresolved, expose
  those exact pages in the editor rather than rewriting the parent translation.
- Risk/effort: medium; this is the highest-value quality fix.

### P1-7 User-visible page boundaries may downgrade raw hard syntax to review

- Evidence:
  - `app/core/utils/podcast_learning_video.py:3175` builds page-boundary syntax
    evidence.
  - Strong pauses or balanced restarts can convert subject/predicate and other
    raw hard issues to `review` around lines 3299-3340.
  - Review pages are allowed to render; they are not publication blockers.
- Historical-package evidence: 7 intra-parent page boundaries carried visible
  syntax review, including `assumptions | about`, `know | how`, and
  `markets | is`.
- Impact: this is a deliberate readability-versus-grammar trade-off, but the
  current policy can publish a visibly awkward page when an alternative plan,
  font, or page count would be better.
- Fix: compare the complete candidate frontier before accepting a raw hard
  boundary. Prefer a strict plan at 56/54/52, then a strict extra page, then a
  review boundary only when no strict candidate exists. Do not make every
  review boundary a blocker.
- Risk/effort: medium; requires fixture and rendered-frame regression coverage.

### P1-8 Release evidence is not tied to the current HEAD

- Evidence:
  - Current HEAD is `55974cc`.
  - The latest complete oil stable run declares `code_commit=a77ec41`.
  - `a77ec41..55974cc` changed 14 files, including roughly 500 lines in the
    screen editor, 96 in the page planner, and 950 in the renderer.
- Impact: the 26-stage code regression proves unit/integration contracts at
  HEAD, but the existing real output cannot prove current end-to-end visual and
  translation behavior.
- Fix: after P1-1 through P1-7, run one fresh blind E2E at the target HEAD and
  require manifest commit equality in the artifact-audit command.
- Risk/effort: low code risk; runtime/API cost is the main cost.

## P2 Findings

### P2-1 Quality signals do not form one closed loop

- The post-final Chinese audit can emit `suggest_llm_reallocation=true`, but it
  runs after the allocation retry owner and does not schedule another retry.
- Editor marks require a narrower code set and confidence `>= 0.85` in
  `app/core/subtitle_processor/subtitle_review_marks.py:327`; therefore a
  multi-signal item such as oil `G0012` at confidence `0.72` is present in the
  report but absent from the focused Chinese editor marks.
- Recommendation: one typed `ReviewIssue` contract should decide retryable,
  editor-visible, blockable, and informational status. A detector should not
  advertise a repair action that no owner consumes.

### P2-2 Legacy bad-cut audit conflicts with the formal boundary evaluator

- `_bad_cut_reasons()` at `screen_editor.py:12091` uses only the last and first
  cleaned tokens and contains sample-derived exact word pairs and adjective
  lists.
- It ignores sentence-terminal context, so complete cues ending in `massive.`
  or `Really?` are reported as suspicious in the oil package.
- A parser/timing-aware formal evaluator already exists and is also run.
- Recommendation: retire the legacy result from actionable counts, or make it a
  compatibility adapter over the formal evaluator. Do not keep growing exact
  word-pair rules.

### P2-3 The old generated-output audit uses an obsolete 14-word hard limit

- `tests/audit_stable_outputs.py:45` defaults to 14 and marks every longer cue
  as `ERROR`.
- Current policy uses 16 as the normal maximum with audited 17-19-word or
  structurally unavoidable exceptions; `tests/caption_audit/metrics.py:104`
  already uses the shared contract.
- `scripts/run_regression.py:243` compiles but does not execute a real manifest
  audit.
- Recommendation: delete or delegate the old implementation to shared metrics,
  then add one temporary-manifest audit covering hashes, IDs, word envelopes,
  page state, and review queues.

### P2-4 Allocation-isolation failure is recorded but does not block publication

- `screen_editor.py:11338` can report `allocation_isolation_failed` when frozen
  English, word ledger, IDs, or other inputs change.
- `has_blocking_validation_errors()` at line 10310 does not consume it.
- Current writeback appears Chinese-only and other gates catch most damage, but
  the explicit invariant is advisory rather than enforced.
- Recommendation: make non-empty changed keys a structural publication error;
  explicitly exclude only documented legal timing updates from the snapshot.

### P2-5 High-frequency manual edits still perform whole-model work

- `_apply_manual_final_session()` calls `to_model_data()` for every local edit.
- A cache hit still deep-copies the complete page model, and
  `update_incremental()` copies/scans old and new rows.
- Complexity: O(n) time and O(n) temporary memory per edit, even if one page
  changed.
- Recommendation: have editor operations return changed parent/page IDs and
  row deltas; update those rows in place and reserve full reset for import or
  view switching.

### P2-6 Durable resume is safe but narrow

- `StableRunStateStore` resumes only article analysis and article ASR
  correction. LLM request caches independently reuse full translation,
  allocation, and page translation, but a process failure still reruns local
  orchestration, boundary planning, alignment, and final validation.
- Recommendation: do not make mutable partial cues resumable. Add an immutable,
  hash-bound checkpoint only after fixed English + parent Chinese is complete,
  then rebuild timing/page projections from that checkpoint.

### P2-7 Core ownership is coupled through private members and duplicated policy

- `subtitle_thread.py:452` reads `screen_editor._final_cue_timeline` and line
  2155 calls private `_subtitle_duration_issues()`.
- `video_synthesis_thread.py:13` imports timing thresholds from
  `screen_editor.py`.
- Formal English and visual-page layers correctly have different owners, but
  shared atomic syntax facts are duplicated in several large modules.
- Recommendation: extract only stable data contracts and pure validators, not a
  broad rewrite of the 19k-line screen editor. This is maintenance work after
  the functional P1 items.

## P3 Findings

- `docs/PIPELINE.md:499` still says 46px Chinese while the renderer and current
  rule are 48px.
- `app/view/home_interface.py:16` hard-codes a white Home background, breaking
  dark-mode consistency.
- Stable-run generations are retained without a documented pruning policy.
  The inspected oil work directory contains 8 runs totaling about 29 MB. This
  is not yet a storage emergency, but should have an explicit retention rule.

## Performance Evidence

The latest measured oil run took `1632.542s`:

- `screen_subtitle_edit`: `1266.354s` (77.6%).
- `display_page_translation`: `296.579s` (18.2%).
- WhisperX time-only alignment: `45.481s` (2.8%).
- Other recorded stages: about 1.4%.

Therefore about 95.8% of elapsed time was inside the two model-backed subtitle
stages. A local DP or Qt micro-optimization will not materially shorten a fresh
full run. First add per-request timing, token/character size, retry count, and
cache-hit evidence; only then decide whether to batch, parallelize, or change a
model role. Manual editor latency is separate and is explained by P2-5.

## Verified Strengths

- Stable mode refuses to fall back to the legacy LLM English editor when a word
  ledger is missing (`screen_editor.py:733`).
- Failed stable attempts publish a checkpoint but do not replace the verified
  root manifest (`subtitle_thread.py:1137`).
- Manual-final save uses an immutable snapshot, generation ownership, hashes,
  and candidate-manifest readback before commit
  (`manual_final_subtitle_editor.py:6583`).
- Saving disables concurrent table mutation and does not make a failed
  publication look successful (`subtitle_interface.py:3395`).
- Manifest-owned paths are constrained to the generation and hash checked
  (`stable_artifacts.py:94`).
- ASR cache identity for FasterWhisper includes the actual command as well as
  audio CRC, and cached data is validated before use.
- Current HEAD passed the complete 26-stage regression before this audit.

## Recommended Repair Order

1. Correctness gate: P1-1, P1-2, P1-3, P1-4, and P1-5.
2. Quality closure: P1-6, P2-1, then P1-7.
3. Audit cleanup: P2-2, P2-3, and P2-4.
4. Editor performance and durable checkpointing: P2-5 and P2-6.
5. One fresh HEAD-bound E2E, then address only the residual evidence from that
   run.

This order avoids another broad rewrite. It repairs ownership and validation
first, then improves visible output through the existing fixed-ID/page
architecture, and leaves lower-risk performance work until correctness signals
are trustworthy.
