# Historical Work-dir Pattern Review

Reviewed: 2026-08-01

## Scope

- 21 latest stable manifests in work-dir.
- Subtitle counts range from 91 to 398 cues.
- Both earlier outputs without an alignment backend record and newer
  whisperx-time-only outputs are included. Older artifacts are evidence of
  recurring failure shapes, not a baseline for current-code pass/fail status.

## Repeated Patterns

1. **Short conversational responses**
   - 299 short-duration warnings across all 21 samples.
   - Most are short acknowledgements, questions, or speaker turns. They should
     remain warnings unless timing is below the dedicated invalid threshold or
     the text load is too high for the available duration.
   - Do not reintroduce global display padding after forced alignment.

2. **Fast reading speed**
   - English speed warnings occur in 20 samples; Chinese speed warnings occur
     in all 21.
   - A warning alone is not reliable evidence of a bad subtitle: short
     questions and natural short responses frequently exceed simple
     words-per-second or characters-per-second thresholds.
   - Only severe Chinese speed remains eligible for local group-only
     compression, with English, IDs, and timing frozen.

3. **English syntax boundaries**
   - The independent post-cut syntax audit reports candidate boundaries in 19
     samples, mainly preposition-object and clause-boundary splits.
   - Snapshot review also found that historical cuts could be marked as a
     preposition-object split and still be accepted when the word-timestamp
     gap was at least 450ms. The current final gate treats that pause as
     evidence only; it no longer overrides hard phrase cohesion.
   - This is a genuine recurring review category, but not yet safe for
     automatic retiming or automatic English rewriting.
   - Future improvement must start with high-confidence local boundary
     generation changes and regression fixtures, not LLM English edits.

4. **ASR name and capitalization uncertainty**
   - Capitalized-variant warnings appear in 17 samples.
   - Article context is the only safe source for automatic canonicalization:
     corrections require an article-evidenced glossary match and remain
     auditable. Generic ASR suspicions stay as warnings.

5. **Chinese cross-cue naturalness**
   - This is visible in historical notes and in the semantic audit, especially
     when a condition, relative clause, or delayed predicate is split across
     consecutive cues.
   - The production remedy is optional fixed-ID semantic-group polish. It must
     use the full group translation as its authority, change Chinese only, and
     be rejected if validation worsens.

## Non-actions

- Do not turn all audit warnings into automatic repairs.
- Do not add text-specific rules for historical sample titles or lines.
- Do not use reading-speed warnings to move WhisperX-owned timing.
- Do not allow ASR suspicion detection to rewrite English without article
  evidence.

## Current Low-risk Priorities

1. Keep stable mode dependent on a valid word-level ledger.
2. Keep one timing owner after final alignment.
3. Keep audit and generation limits shared.
4. Use historical examples only as generic regression fixtures after they are
   reduced to language structures rather than copied sentences.
