# Pipeline

## Stage 1: Transcription

Input:

- Audio file.

Output:

- Original ASR subtitle file.
- Word-level timestamp data when enabled.

Important rules:

- CUDA should be preferred when available.
- ASR may miss speech or create overly short word timings.
- Word-level timestamps are useful but not perfectly reliable.

## Stage 2: Stable English Segmentation

Input:

- Word-level timestamp sequence.

Output:

- Stable English subtitle segments.

Rules:

- English text is restored locally from word ranges.
- LLM must not rewrite, delete, reorder, or invent English.
- Preferred visual target is 6-12 words; the normal hard maximum is 16. A 17-19 word exception requires an audited parser-confirmed grammar constraint. When an otherwise complete terminal source sentence has no legal normal-limit temporal cut, it remains one renderer-owned cue and is reported as a structural reading warning rather than being cut into a fragment.
- Preserve source order and token coverage.
- Prefer clause, punctuation, discourse, and phrase boundaries.
- Avoid cutting after prepositions, articles, auxiliaries, or connectors.
- The 12-word/68-character visual reading target never creates a formal cue
  boundary. A long, grammatically complete cue remains one fixed English item
  until renderer-only pagination projects it into readable pages. That display
  projection cannot change fixed IDs, Chinese allocation, SRT/ASS, or timing.
- The same pre-ID finalizer may rebalance a short, parser-confirmed non-finite
  conditional prefix from the start of one cue to the preceding incomplete
  clause. It requires continuity, one speaker, a sub-450ms pause, a complete
  following main clause, and both resulting cues within the hard word limit.

## Stage 3: Semantic Chinese Translation

Input:

- Fixed English subtitle segments.
- Semantic groups built from adjacent English parts.

Output:

- Chinese subtitle per fixed English part.

Rules:

- Full group translation comes first.
- Allocation maps the full Chinese meaning back to fixed global subtitle IDs.
- English IDs, timing, and order are immutable during Chinese translation.
- Missing Chinese is a validation issue.
- LLM allocation responses must include `subtitle_id` for each returned Chinese line.
- Returned, missing, duplicate, and unknown subtitle IDs are recorded as structure errors.

## Stage 4: Timing and Display Stabilization

Input:

- Fixed English/Chinese subtitle segments.

Output:

- Final display-timed subtitle segments.

Rules:

- The final word ledger is the only timing authority after English boundaries
  and IDs are frozen.
- Each final cue is derived from its own `subtitle_id -> [word_start, word_end]`
  envelope. WhisperX may update ledger word times but cannot map final cue text
  to a separate time range.
- A padding overlap may be reconciled only at a shared boundary that stays
  between the adjacent word envelopes.
- Do not change English text, Chinese text, subtitle ID, word range, or order.
- Missing, duplicate, unknown, or synthetic final timeline IDs are ERRORs and
  block export.

## Stage 5: Validation and Artifacts

Outputs:

- `*-coverage-report.txt`
- `*-artifacts/`
- `validation-report.json`
- `translations.json`
- `subtitle-spans.json`
- `word-ledger.json`
- `semantic-groups.json`
- `allocation-inputs.json`
- `allocation-raw-returns.json`
- `allocation-validation.json`
- `allocation-retry-log.json`
- `allocation-final.json`
- `allocation-unresolved.json`
- `translation-structure-errors.json`
- `final-cue-timeline.json`
- `english-boundary-audit.json`
- `run-state.json`

Run-state rules:

- It is a progress/recovery record, never a subtitle source of truth.
- It hashes the input subtitle, article state, relevant stable configuration,
  model/prompt values, and selected timing backend.
- A stage artifact is reusable only when its recorded digest and full input
  fingerprint match; otherwise the normal stage executes.
- Existing LLM batch caches may be reused under their current cache keys, but
  completion order never controls translation or subtitle writeback order.

Validation checks:

- English coverage gaps.
- Whole-file English boundary audit: `hard` atomic splits with no contrary
  timing/speaker evidence must be repaired before IDs; residual `hard` items
  block export. Ambiguous `review` items are retained for human verification;
  independently supported `allow` boundaries remain untouched.
- Missing Chinese.
- Overlong English.
- Translation ID mismatch, missing ID, duplicate ID, unknown ID, or group cardinality mismatch.
- Suspicious cuts.
- Timing gaps and very short displays through audit scripts.

## Stage 6: Stable Final Subtitle Outputs

Output files:

- `stable-final-original-top.srt`
- `stable-final-translation-top.srt`
- `stable-final-only-original.srt`
- `stable-final-only-translation.srt`
- `stable-final-manifest.json`

Rule:

- Video synthesis should use the manifest path first.
- Do not rely on fuzzy localized file-name search when a manifest exists.

## Stage 7: Video Synthesis

Input:

- Audio/video media.
- Stable final SRT from manifest.

Output:

- Podcast learning video.

Rule:

- If rendered subtitles are wrong, first verify the resolved subtitle path.
- The article-template renderer must verify the stable manifest, final cue
  timeline, and word ledger before synthesis. It plans fixed 58px English and
  46px Chinese pages inside each frozen cue. It first keeps a whole cue on one
  static page using measured pixels: the normal 1455px English panel, then the
  1498px safe-width profile, with at most two English and two Chinese lines.
  Chinese character count alone never creates a page. Only an actual
  fixed-font overflow may require a timed page; those transitions switch only
  at ledger word gaps and require at least 900ms per page. Missing or
  mismatched timing, fixed-font overflow, or an unschedulable page raises
  `render_structural_overflow` before ffmpeg starts.
