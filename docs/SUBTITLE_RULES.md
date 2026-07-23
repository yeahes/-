# Subtitle Rules

## English

- English subtitle text must match the audio transcript.
- Stable mode must not rewrite English for style.
- Stable mode must not delete filler or backchannel words by default.
- If a short backchannel is visually too brief, merge or extend display timing instead of deleting it.
- Target maximum is 14 English words per subtitle.
- If a rare case cannot satisfy both 14 words and grammatical integrity, preserve grammatical integrity first and report the issue.

## English Cutting

Good cut points:

- Sentence punctuation.
- Natural clause boundary.
- Before or after contrast markers when the previous part is complete.
- Around examples or appositives.
- After a complete subject-verb-object unit.

Bad cut points:

- After `of`, `for`, `with`, `by`, `to` when the object follows.
- Between article and noun.
- Between adjective and noun.
- Between auxiliary and main verb.
- Between number and unit.
- Inside names, institutions, or fixed terms.
- Immediately after `because`, `which`, or `that` when the dependent content follows.

## Chinese

- Chinese should be natural Simplified Chinese.
- Preferred style: concise magazine, documentary, finance/explainer narration.
- Do not translate word-for-word in English order when Chinese would become stiff.
- Preserve facts, numbers, names, negation, modality, contrast, condition, and speaker stance.
- Do not move information earlier than the corresponding English audio.

## Timing

- Final display timing may extend subtitles for readability.
- Final timing must not overlap adjacent subtitles.
- Short spoken beats can be bridged to the next subtitle when the gap is small.
- A large blank gap must be treated as a possible ASR/timing issue and reported.

## Validation Policy

Blocking errors:

- Missing Chinese for an English subtitle.
- Severe continuous subtitle coverage gap.
- Time order corruption.
- Overlong English that violates configured hard limits.

Warnings:

- Suspicious cuts.
- Very short display duration.
- Small timing gaps.

## Avoided Approaches

- LLM jointly deciding English segmentation and Chinese translation.
- Deleting `Right`, `Yeah`, `Exactly`, etc. to make subtitles cleaner.
- Fixing every sample by adding one-off text-specific rules.
