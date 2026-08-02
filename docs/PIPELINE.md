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
- Preferred visual target is 6-12 words; the normal hard maximum is 16. A 17-19 word exception requires an audited parser-confirmed grammar constraint.
- Preserve source order and token coverage.
- Prefer clause, punctuation, discourse, and phrase boundaries.
- Avoid cutting after prepositions, articles, auxiliaries, or connectors.

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

- Do not change English text.
- Merge very short spoken beats only when safe and under length limit.
- Apply minimum display duration when room allows.
- Bridge short display gaps when the next subtitle follows soon.
- Do not overlap adjacent subtitles.

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

Validation checks:

- English coverage gaps.
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
