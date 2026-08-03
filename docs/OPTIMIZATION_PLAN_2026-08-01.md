# Stable Subtitle Optimization Plan

## Objective

Improve production reliability for English-learning bilingual subtitles without
allowing LLM output, legacy repair code, or video rendering to change frozen
English text, subtitle IDs, or final aligned timing.

## Non-Negotiable Invariants

- English words, order, subtitle IDs, and aligned timestamps are immutable after
  local stable segmentation.
- Chinese is written back only by subtitle ID.
- A missing, duplicate, or unknown Chinese ID blocks rendering.
- WhisperX time-only owns final timing when selected; later stages cannot pad or
  shift its cue boundaries.
- ERROR blocks synthesis; WARNING is visible but does not rewrite output.
- No sample-specific text rules for historical audio files.

## Phases

1. **Baseline and acceptance**
   - Record current samples, manifests, SRT hashes, validation counts, timing,
     cache state, and manual review findings.
   - Acceptance: results are reproducible and stale artifacts are labelled.

2. **Stable-path boundary cleanup**
   - Map every production call into `screen_editor.py`.
   - Remove stable-path calls to legacy free translation, timing mutation, and
     experimental auto-repair. Keep compatibility code isolated until covered.
   - Acceptance: one English writer, one timing owner, one Chinese ID writer.
   - Status: completed for the production route. Stable mode now forces the
     word-level ledger and blocks explicitly when the ledger cannot be formed.

3. **Article-aware ASR integrity**
   - Improve high-confidence article entity correction and add an explicit
     review signal for obvious grammatical/entity mismatches not safely fixed.
   - Acceptance: correction never changes unrelated words and every edit is
     auditable.

4. **Chinese semantic-group quality**
   - Keep whole-group translation as the authority, then allocate by fixed ID.
   - Run optional local-risk detection and limited group-only polishing.
   - Acceptance: no English/timing changes, no ID drift, only strict quality
     improvements are accepted.
   - Status: optional selective polish is implemented and guarded by fixed-ID
     validation. It now also receives fixed-time Chinese display budgets and
     can select a capped complex enumeration/comparison group class. Audit
     false positives for the Chinese negation 并非 and sentence-final 是的 were
     reduced before allowing it to select LLM work.

5. **Diagnostics and optional video features**
   - Reduce audit false positives, make failure reasons visible, and ensure
     vocabulary-card failures are partial and observable.
   - Acceptance: a failed optional feature cannot silently alter or block
     subtitle output.

6. **End-to-end validation and freeze**
   - Run unit tests, rule regression, multiple real samples, timing audits, and
     at least one rendered video with a fresh result.
   - Acceptance: no structural ERROR, no English/Chinese ID mismatch, no
     timestamp overlap, and manual review shows no regression against baseline.

## Latest Generic Segmentation Guard

- A long word-level pause is evidence for a possible boundary, not permission
  to split an unbreakable English phrase.
- The stable final gate keeps hard grammar boundaries illegal even when the
  aligned pause is at least 450ms. It covers preposition-object,
  determiner/numeric-noun, quantifier, numeric-unit, auxiliary-predicate,
  determiner-head, and time-range continuations.
- Regression coverage includes a 500ms pause at `about | finding`; the cut
  must remain illegal. This is structural and does not depend on any specific
  source audio.

## Latest Deterministic Cutting Policy

- The stable path now uses deterministic local candidate selection; it does not
  introduce dynamic programming.
- 16 English words is the normal display target. A 17-19 word cue is permitted
  only if no shorter grammar-safe boundary exists. No cue may grow beyond 19
  words merely to avoid a cut.
- spaCy dependency hints additionally reject a line break immediately after a
  subordinate-clause introducer and between a verb and its attached
  preposition complement. These checks are grammar-class based, not tied to a
  historical transcript.
- A small final merge prevents an 18-word cue followed by a one-word orphan
  when their combined 19-word phrase is the only grammar-safe display unit.

## Test Commands

```powershell
runtime\python.exe tests\test_stable_caption_rules.py
runtime\python.exe tests\test_rule_regression_library.py
runtime\python.exe scripts\run_regression.py
```

## Baseline Snapshot (2026-08-01)

- Recent production outputs consistently use `whisperx-time-only` and show no
  translation-ID structure errors.
- The latest short sample (`美国已成为`, 103 cues) passed with no ERROR.
- Longer existing samples still produce a high WARNING volume; warnings cannot
  be treated as an automatic repair queue.
- Two historical samples remain render-blocked by reading-speed ERROR and must
  be regenerated before they are used as current-code evidence.
- Current offline re-audit of 美国已成为 (102 cues) reports 0 ERROR and 16
  WARNING. The remaining warnings are review signals only; this audit did not
  regenerate or modify subtitle output.

## Scope Control

- Do not introduce dynamic programming in this cycle.
- Do not split `screen_editor.py` until fixture coverage protects its stable
  behavior.
- Do not let the audit automatically repair WARNING findings.
- Do not score a new version higher until it passes a fresh, previously unused
  audio sample.
