## 2026-08-21 High-Value Manual Review Queue

- Added a frozen, ID-addressable editor review ledger. Cross-ID evidence is one
  human task, and category-specific cell colors/tooltips distinguish English,
  Chinese, timing, and page work without changing subtitle content.
- Added post-page OpenCode Flash audits for accuracy/ASR, Chinese fluency/page
  load, and adjacent mapping/continuity. Forty-target batches are cached
  independently; complete target-ID coverage is required in all three passes
  and an incomplete audit blocks completion.
- Model results remain read-only. Actual page load is verified locally, valid
  short responses and omitted conversational fillers are excluded, and noisy
  local semantic heuristics become fallback evidence after a full model audit.
- Fixed article-review ownership so valid demonyms and canonical names already
  present in a cue do not become manual ASR tasks.
- White House is the current three-stage baseline; Dreamcore is a legacy missed-
  class sample. Live audits were read-only and did not rewrite either artifact.
- A complete two-pass rerun still missed the known `S0075` cross-row defect, so
  continuity/mapping now has a dedicated third pass and a new prompt/cache
  version instead of relying on one overloaded fluency pass.
- The first three-pass replay recovered `S0075` but incorrectly reported
  omitted `Absolutely`/`Exactly` responses. Semantic and ASR findings now carry
  an exact source quote so local validation can reject ungrounded evidence and
  optional discourse-marker omissions.
- Cross-row coherence now requires exactly two adjacent fixed IDs. The
  validator accepts an adjacent batch-context ID only when the issue also owns
  a target ID, preventing both single-row mislocation and batch-edge blind
  spots.
- The v4 White House replay covered 217/217 IDs with no batch error and bound
  `S0074`/`S0075` as one task. A final local evidence check removes semantic
  findings whose reason cites only optional discourse markers, even if the
  model quoted a longer surrounding sentence.
- The final read-only queue contains 31 deduplicated human tasks across 36 of
  217 White House subtitle IDs. The complete 30-check offline regression passes
  in 929.70 seconds. A new GUI click-to-editor-to-save-to-synthesis run remains
  required before treating the 95% automation target as production-verified.

