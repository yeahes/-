# Subtitle Quality Ceiling Roadmap

Status: in progress; context and source-echo translation increments implemented
Last researched: 2026-08-12
External reference snapshot: SmartSub `27459b3fd0652bc5447ccf4ab30cb398014c35f7`

## Purpose

Record the remaining high-value work required to approach publication-quality
English-learning podcast subtitles without repeatedly re-auditing SmartSub or
reconstructing decisions from chat history.

The practical target is:

- roughly 85-90 quality points from an unseen audio run without manual edits;
- roughly 93-96 after a focused review of a small risk queue;
- no claim that arbitrary unseen audio can reach 95 automatically.

The score is not a structural pass rate. A subtitle can preserve IDs, timing,
numbers, and non-empty Chinese while still mistranslating speaker intent or
reading like literal machine translation.

## Current Evidence

The 257 visible cues in the 2026-08-12 `Hollywood age-gap romance` manual
package produced about 19 priority translation findings and 17 secondary
fluency findings during a full read. This is audit evidence, not a permanent
benchmark or a claim that every unlisted cue is perfect.

The same package exposed an ownership mismatch at `S0057`:

- `translations.json` and `display-page-translations.json` contained the
  improved wording corresponding to `the public suddenly realizing ...`;
- the parent manual-final SRT still contained the older literal wording
  corresponding to `a sudden public revelation`.

Therefore the remaining ceiling is not only model quality. It also includes
state propagation and artifact authority.

Current full-translation requests contain the active semantic group's full
English and current Chinese. The prompt may include article summary/terms, but
the payload does not explicitly identify bounded previous/next dialogue turns
as read-only context. Existing deterministic gates are strongest at cardinality,
IDs, empty values, entities, numbers, negation, duplication, and fragments.
They do not reliably reject a complete but contextually wrong or stiff Chinese
sentence.

## Invariants

Every increment below must preserve:

- one authoritative word ledger;
- frozen English word order, subtitle IDs, word spans, and word timestamps;
- local deterministic stable-mode English segmentation;
- Chinese writeback by exact parent or display-page ID;
- one manifest-owned final subtitle path for synthesis;
- fail-closed structural validation;
- manual edits as explicit higher-priority overrides, never silent cache data.

An LLM may propose Chinese or a human-visible boundary suggestion. It may not
own stable English text, IDs, word timing, or automatic final cue boundaries.

## Selected Architecture

### 1. Repair translation state ownership first

Create one versioned authoritative Chinese record per fixed parent ID. Parent
SRT Chinese, fixed-ID allocation, display-page Chinese, editor rows, and the
manual-final package must either derive from that record or carry an explicit
manual override with its own version and source hash.

On save and import, validate:

- parent English hash and word span;
- authoritative Chinese version/hash;
- page contract hash and exact page IDs;
- manual override provenance;
- final SRT and display artifact agreement.

A stale parent translation must not overwrite a newer page translation, and a
new automatic translation must not overwrite an explicit manual correction.
Surface the conflict instead of choosing by file timestamp.

### 2. Add bounded document and dialogue context

For each target semantic group, send:

- the target group's immutable ID and full English;
- previous and next two or three semantic groups as `context_only`;
- speaker label or turn boundary when available;
- article topic summary and evidenced terminology;
- the current translation when revising rather than translating fresh.

The response schema must contain only the target ID. Neighboring context is not
translated or written back. This improves word-sense, pronoun, stance, irony,
power-relation, and discourse-marker decisions without allowing cross-ID drift.

### 3. Add selective semantic review

Do not run an unconstrained second rewrite over every cue. Build a deterministic
risk queue, then ask an independent reviewer only about high-risk groups.

Useful risk evidence includes:

- ambiguous or domain-sensitive words;
- sexual, legal, financial, medical, identity, or power-relation language;
- source English that is grammatically unusual or low-confidence;
- a large mismatch between literal anchors and current Chinese phrasing;
- translationese patterns, incomplete logic, or conflicting neighbor stance;
- a manual history pattern showing repeated corrections for the same class.

The reviewer receives the same context envelope and returns `accept` or one
replacement for the same target ID plus machine-readable issue codes. Candidate
acceptance must preserve facts, names, numbers, negation, modality, speaker
stance, and all fixed contracts. Rejected review candidates leave the first
translation unchanged and remain visible for human review.

### 4. Isolate batch failures and repair exact IDs

Use an exact dynamic response schema for the current ID set, source echo
anchoring, normalized source similarity, and per-entry repair. If a small
number of entries fail, retry only those entries with previous/next context.
If more than one third of a batch has structural failures, retry the batch once
before falling back to per-entry repair. One failed entry must not poison a
valid batch.

This extends the project's existing fixed-ID validation; it does not replace
it. Weak semantic suspicions create review evidence, not automatic failure.

### 5. Make terminology persistent and economical

Maintain ordered terminology sets with `source`, `target`, and optional `note`.
Resolve conflicts by explicit priority, log the kept and ignored entry, and
inject only terms actually matched in the current source/context window.

Article-derived terms remain evidence-bound candidates. They must not become
fuzzy rewrite authority merely because a later article occurrence resembles an
ordinary phrase in the audio.

### 6. Turn the editor into a focused publication checkpoint

The editor should prioritize a queue containing only:

- likely semantic mistranslation;
- translationese or context ambiguity;
- unresolved page-Chinese alignment;
- suspicious source/ASR text;
- dense or low-font display pages;
- explicit structural blockers.

For the selected item, show adjacent dialogue, authoritative full Chinese,
current fixed-ID/page Chinese, review suggestion, word chips, timing evidence,
and exact rendered preview. Preserve selection and scroll position after every
operation.

Use parent/range-scoped command deltas for undo/redo, an atomic working-draft
autosave, crash recovery, and an explicit publish action. Exploratory edits do
not rebuild or publish the complete manual package.

### 7. Keep AI segmentation suggestion-only

When deterministic long-caption candidates all remain high risk, an optional
LLM may insert boundary markers into verbatim English. Acceptance requires
normalized text equality, legal existing word-ID boundaries, and unchanged
word coverage/order/times. The result is a human-visible alternative only and
is never applied automatically in stable mode.

### 8. Build a real quality benchmark

Create a versioned, privacy-safe regression set from accepted and rejected
historical cases. Store minimal English/context/expected-Chinese evidence rather
than private full production journals.

Measure separately:

- semantic accuracy and speaker stance;
- natural Chinese and translationese;
- terminology consistency;
- fixed-ID and display-page alignment;
- structural invariants and timing;
- human review count and editing time;
- latency, cache hit rate, and paid token cost.

Do not claim 95 until at least one cached regression corpus and multiple unseen
audio topics pass a blind review. ASR omissions or incorrect source English
remain an upstream ceiling and must be reported separately from translation.

## SmartSub Patterns To Adapt

The following were verified against SmartSub main at the pinned commit above.
They are patterns to adapt, not code to copy into the Python/Qt architecture.

| SmartSub pattern | Adaptation in this project | Reason |
| --- | --- | --- |
| Dynamic JSON schema with exact batch IDs | Apply to high-risk review and page-Chinese suggestions | Prevent missing, extra, or shifted IDs before writeback |
| `{src, tr}` source echo and similarity validation | Echo frozen parent/page English and verify it locally | Detect model merge or response drift deterministically |
| Per-entry repair with previous/next two subtitles | Repair only the failed fixed ID with bounded read-only context | Improves context while isolating failures and cost |
| Batch retry only when failures exceed one third | Preserve good results and retry the smallest unsafe unit | Avoid one bad line rerunning or corrupting a full batch |
| Strong/weak untranslated evidence | Strong evidence can trigger repair; weak evidence becomes review-only | Avoid false failures on names, numbers, or related languages |
| Ordered glossary, conflict logging, hit-only injection | Add persistent project/domain term sets beside article terms | Improve consistency without wasting context tokens |
| 300-500 unit windows cut near the largest trusted gap | Use only for analysis/review request batching | Keep context coherent without moving production boundaries |
| Verbatim `<br>` protocol plus equality validator | Optional manual boundary alternative only | Gain semantic suggestions without surrendering English authority |
| Range-diff command history capped at 200 | Replace repeated whole-document editor snapshots with parent/page deltas | Lower memory, make undo/redo local, and improve recovery |
| Persistent proofreading tasks and unsaved-change guard | Autosave draft state and resume at the previous item | Prevent lost manual work and reduce repeated review |
| Video-linked editor and WYSIWYG preview | Reuse the project's exact article renderer in the focused workspace | Show the real bilingual page rather than a generic row estimate |

## SmartSub Patterns Not To Adopt Directly

- Do not replace stable local English segmentation with SmartSub's optional LLM
  segmentation.
- Do not delete spoken fillers or backchannels globally.
- Do not use a generic subtitle-row model as timing authority; this project
  requires word-ledger, parent-ID, page-ID, and manifest ownership.
- Do not add many translation providers as a substitute for better context,
  review, and state consistency.
- Do not fall back silently to a lower-quality provider and call the result a
  successful publication translation.
- Do not bypass the stable manifest with a generic FFmpeg burn-in path.
- Do not copy TypeScript/Electron code into Python/Qt; port the contract and
  test the behavior at the owning layer.

## Implemented Since This Plan Was Recorded

- Full-group translation requests now carry up to two previous and two next
  semantic groups as `context_only` read-only entries. The target response is
  still exact-ID validated, and neighboring text is never written back.
- The existing selective fixed-ID Chinese polish path receives the same bounded
  context envelope. Its candidate comparator remains the sole write gate.
- The context contract is versioned as
  `semantic-full-translation-context-v1` in cache metadata and manifests.
- Full-group translation responses now must echo the exact target group's
  English word sequence as `source_english`. Missing or mismatched echo marks
  only that group for single-group retry; valid neighboring groups remain
  usable. The contract is versioned as
  `semantic-full-translation-source-echo-v1`.
- Display-page translation requests now carry and validate the exact page
  English as `source_english`. Missing or mismatched page echoes invalidate
  only the page translation response and force the existing bounded retry;
  legacy artifacts remain readable when the new flag is not requested.

## Delivery Order

1. Reproduce and fix authoritative-Chinese/manual-final synchronization.
2. Add context-only neighbor envelopes and hit-only terminology injection.
3. Add exact-ID source echo and local per-entry repair where missing. (Source
   echo and per-group retry are now implemented for full translations.)
4. Add selective semantic review and the editor risk queue.
5. Add delta journal, autosave/recovery, and exact preview workflow.
6. Add optional verbatim boundary alternatives only after the above is stable.
7. Run cached regressions, then blind unseen-audio E2E before raising the
   quality claim.

Each delivery step requires a root-cause regression at its owning layer plus
the unified regression. Translation-only work must not change English, the
word ledger, timing, page geometry, or synthesis resolution.

## Cost And Trade-offs

- More context increases input tokens, but a bounded neighbor envelope and
  hit-only glossary keep it predictable.
- A selective reviewer adds requests only for risky groups; a whole-file third
  translation pass is intentionally rejected.
- Source echo increases output tokens but provides deterministic alignment
  evidence.
- Strong automatic semantic gates risk false positives, so uncertain findings
  remain review items rather than publication blockers.
- Better automatic translation reduces manual work but does not remove the
  need for a final human publication decision.

## References

- SmartSub repository snapshot:
  https://github.com/buxuku/SmartSub/tree/27459b3fd0652bc5447ccf4ab30cb398014c35f7
- Translation alignment specification:
  https://github.com/buxuku/SmartSub/blob/27459b3fd0652bc5447ccf4ab30cb398014c35f7/openspec/specs/ai-translation-alignment/spec.md
- AI subtitle segmentation specification:
  https://github.com/buxuku/SmartSub/blob/27459b3fd0652bc5447ccf4ab30cb398014c35f7/openspec/specs/ai-subtitle-segmentation/spec.md
- SmartSub range-diff undo history:
  https://github.com/buxuku/SmartSub/blob/27459b3fd0652bc5447ccf4ab30cb398014c35f7/renderer/hooks/useSubtitleHistory.ts
- SmartSub glossary core:
  https://github.com/buxuku/SmartSub/blob/27459b3fd0652bc5447ccf4ab30cb398014c35f7/main/glossary/core.ts
- SmartSub proofreading editor:
  https://github.com/buxuku/SmartSub/blob/27459b3fd0652bc5447ccf4ab30cb398014c35f7/renderer/components/proofread/ProofreadEditor.tsx
- DeepL translation context parameter:
  https://developers.deepl.com/api-reference/translate

## Future Reading Rule

Read this file first. Re-open SmartSub source only when implementing one of the
pinned patterns, checking an upstream change after the pinned commit, or
verifying a disputed technical detail. Do not re-audit the whole repository for
ordinary planning or status questions.
