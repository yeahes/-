# Subtitle Rules

## English

- English subtitle text must match the audio transcript.
- Stable mode must not rewrite English for style.
- Stable mode must not delete filler or backchannel words by default.
- If a short backchannel is visually too brief, merge or extend display timing instead of deleting it.
- Preferred visual target is 6-12 English words per subtitle.
- Normal hard maximum is 16 English words. A rare 17-19 word structural exception is allowed only when every shorter cut would create a parser-confirmed grammar error; report the exception. If an otherwise complete terminal source sentence has no legal normal-limit temporal cut, preserve that complete cue for renderer wrapping and report its structural overflow rather than force a fragment at 19 words.
- The 12-word / 68-character reading target belongs only to the renderer.
  A complete 13-16 word English cue remains one temporal subtitle with one ID
  and one Chinese allocation. A visual word/character budget, renderer, or
  template must never create or move a formal subtitle boundary.
- Rendering may paginate a frozen cue for readability, but that projection
  cannot alter English text, subtitle IDs, word spans, cue times, Chinese
  allocation, SRT, or ASS output.
- A short comma-terminated non-finite condition at the start of a cue may move
  back to the immediately preceding clause only when local parsing confirms it
  has a clause marker but no subject or finite predicate, the following text is
  a complete main clause, the pause is under 450ms, and both repaired cues stay
  within the English word limit. A finite conditional introduction remains in
  its own cue. The audit records any narrowly accepted syntax exception.

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
- A residual `hard` English boundary: an atomic structural split without
  sentence-terminal, long-pause, speaker-change, or discontinuous-ledger
  evidence. Pre-ID repair owns automatic resolution; final residuals block
  export rather than silently merging fixed IDs.

Warnings:

- Suspicious cuts.
- `review` English boundaries: plausible but ambiguous fragments or atomic
  shapes contradicted by pause/speaker evidence. They are recorded for human
  review, not auto-merged.
- Very short display duration.
- Small timing gaps.

Allowed boundaries:

- Independently readable cues supported by sentence punctuation, a pause,
  speaker change, or local context. A cue starting with `But`, `Because`,
  `In`, or a finite verb is not invalid by word class alone.

## Avoided Approaches

- LLM jointly deciding English segmentation and Chinese translation.
- Deleting `Right`, `Yeah`, `Exactly`, etc. to make subtitles cleaner.
- Fixing every sample by adding one-off text-specific rules.
