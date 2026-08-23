# Recent Actual-Page Subtitle Quality Audit

Verified: 2026-08-23 01:28:22 Asia/Shanghai
Verified HEAD before documentation: `6104934`
Scope: read-only audit of saved stable artifacts; no program, test, subtitle,
audio, cache, or `work-dir` artifact was changed.

## Bottom Line

The current pipeline is not generally worse because one newer White House run
looks worse than an older White House run. Those two runs contain different
audio and different word ledgers, so they are different held-out samples, not a
same-input regression test.

The pipeline nevertheless has a verified regression/stability problem. The
Chocolate `v27` and `v29` runs have the same authoritative word ledger but
different parent spans and page behavior: `v27` passes, while `v29` blocks on
two parents and two missing page-Chinese rows. Both manifests report the same
Git commit even though their planner versions differ. Therefore the exact
runtime implementation cannot be reproduced from `code_commit` alone.

The main quality limit is not one wrong global stage order. It is five narrower
ownership failures:

1. Run inputs and review artifacts are not fully isolated by media/run identity.
2. The pre-ID English boundary owner still accepts obvious cross-cue dependency
   splits, while its audit reports unrelated false positives.
3. Page planning mixes hard renderability with soft style preferences, turning
   some watchable short terminal pages into whole-parent blockers.
4. Parent Chinese can be correct while page Chinese is missing, fragmented,
   duplicated, or assigned to the wrong English page.
5. Review marks do not always prove that their evidence belongs to the current
   word ledger and English text.

On the newest White House sample, estimated visible-page readiness is about
`88%-91%`. This uses all 271 frozen display-page slots and manual inspection of
parent context, English pages, Chinese pages, and neighboring pages. It is not
a vendor benchmark. Difficult multipage-parent readiness is only about
`55%-65%`, and 59/221 parent IDs (`26.7%`) enter the editor queue. This does not
meet the target of `90%-95%` automation with at most about `10%` human review.

## Audit Method

For every manually inspected item, the audit compared:

- the previous, current, and next frozen parent subtitle;
- the parent English boundary and complete meaning unit;
- the authoritative parent Chinese;
- every actual `Sxxxx.Pxx` English page and its word range, duration, font, and
  page-boundary evidence;
- every page-local Chinese row and its correspondence to the English page;
- the frozen review ledger and the evidence artifact that produced the mark.

Program `PASS`, `ERROR`, or yellow highlighting was treated only as evidence,
not as the quality conclusion. Manual-final outputs were kept separate from raw
automatic checkpoints.

## Case Inventory

| Case | Raw artifact | Parent/page shape | Formal state | Human-work signal |
| --- | --- | --- | --- | --- |
| White House B, newest and different audio | `stable-checkpoints/20260822T234803.890133-6f244e63` | 221 parents, 271 pages, 42 multipage parents | `ERROR`; 3 unpageable parents and 5 missing page-Chinese IDs | 59/221 IDs, `26.7%` |
| White House A, different audio | `stable-runs/20260821T230939.708705-4e6f51c9` | 217 parents, 261 pages, 39 multipage parents | `PASS` | 16/217 IDs, `7.4%` |
| Dreamcore, historical pre-three-stage | `stable-runs/20260820T032934.469932-d1a44697` | 202 parents, 247 pages, 38 multipage parents | `PASS` | about 5/38 long parents visibly need work |
| Employment raw checkpoint | `stable-checkpoints/20260821T145313.192574-4fbdb7bc` | 260 parents, 287 pages, 26 multipage parents | `ERROR`; mixed geometry and page-Chinese failures | 26/260 IDs, `10.0%`; later manual final is separate |
| Chocolate `v27` | `stable-runs/20260821T095357.545965-d8d99059` | 230 parents, 258 pages, 25 multipage parents | `PASS` | 13/230 IDs, `5.7%` |
| Chocolate `v29`, same input as `v27` | `stable-checkpoints/20260822T013841.567135-4734ae40` | 221 parents, 254 pages, 30 multipage parents | `ERROR` | 40/221 IDs, `18.1%` |
| Japanese X-generation | `stable-checkpoints/20260822T081526.304594-8536fe61` | 241 parents, 305 pages, 51 multipage parents | `ERROR`; page-number anchor failure at `S0136` | 55/241 IDs, `22.8%` |

All paths are below the matching title in `work-dir/<title>/subtitle/`.
Dreamcore predates the completed three-stage contract and is a style/reference
sample, not a fair current end-to-end score.

## New White House Findings

### Reproducible artifact facts

- Authoritative word ledger: 2,586 words, hash
  `07a8d2473d53bf5e34b0afbe987f5bbd8528d25015f6fd2f5cb777a469f90ec0`.
- Page plan: 271 pages; 42 parents use 92 multipage slots.
- Page projection: 87/92 multipage Chinese rows returned. Missing:
  `S0083.P01/P02` and `S0097.P01/P02/P03`.
- No normal-font complete partition: `S0123`, `S0133`, and `S0193`.
- Twelve planned page slots exceed 16 words. Seven multipage parents have a
  largest-to-smallest page word-count difference of at least nine words.
- The editor ledger contains 58 tasks: 53 `REVIEW`, 5 `BLOCKER`, affecting 59
  unique parent IDs.

### Parent English boundary defects

These are visible formal-cue defects, not merely optional page improvements:

| Boundary | Why it is defective |
| --- | --- |
| `S0003 -> S0004`: `for anyone | just walking ...` | one participial modifier is split from its head |
| `S0106 -> S0107`: `technical chapters | called rules of origin` | attached post-noun modifier is stranded |
| `S0125 -> S0126`: `puts Navarro's numbers up | against ...` | separable verb/preposition chain is split |
| `S0153 -> S0154`: `the delivery truck ... | was financed ...` | subject is split from its finite predicate |
| `S0207 -> S0208`: `hasn't come | to pass ...` | fixed complement chain is split |
| `S0211 -> S0212`: `global supply | chain ...` | one lexical compound is split |

The saved English-boundary audit classifies all six as `allow`. Its ten parent
`review` records instead cover complete sentence changes, question/answer
changes, or ordinary discourse restarts. The editor retains seven of those ten.
For this explicitly labeled White House subset, parent-boundary marking has
`0/7` precision and `0/6` recall. This is a category/sample metric, not a
whole-project score.

### Actual display-page defects

High-value examples include:

- `S0029`: 10+18 words; the second page begins with an attached relative
  clause and is denser than the first.
- `S0031`: the comparison `between China | and the rest of the world` is split,
  and page Chinese becomes `中国 | 与其他国家...`.
- `S0037`: 8+18 words; `carries | a huge financial penalty` splits verb/object.
- `S0072`: `describes ... | as the financial engine` splits the predicate
  complement.
- `S0081`: four pages preserve word order but the final Chinese sequence ends
  `看似无用，别拆。 | 弄清当初用途前`, reversing the natural condition/action
  order during viewing.
- `S0097`: 15+5+6 words and all three page-Chinese rows are missing.
- `S0113`: `rules of origin just | for the Trans-Pacific Partnership` creates
  both an English dependency split and unnatural Chinese page order.
- `S0202`: 16+6 words; `set | a maximum threshold` splits verb/object.
- `S0221`: 16+13 words; the subject ends page one and `is nearly meaningless`
  starts page two.

The visual-page yellow marks are substantially more useful than the parent-cut
marks. Most identify real long-caption ambiguity, but some are watchable
punctuation- or pause-supported continuations. Current evidence supports an
estimated `65%-80%` actionable precision for visual-page marks, not an exact
golden-label score.

### Chinese defects

Confirmed parent or cross-page examples:

- `S0049`: `water ... part of the bed` is translated as `河床`, losing the
  waterbed metaphor.
- `S0145` and `S0192`: textual `source` is translated as `消息人士`.
- `S0166`: `这个运作的规模大得惊人。巨大。` is literal and unnatural.
- `S0219 -> S0220`: `without respecting | why those rules...` becomes
  `除非先理解一点 | 这些规则...为何...`, which does not read as one natural
  Chinese sentence.
- Multiple page projections are locally faithful but place modifiers,
  conditions, or comparison halves on pages where the Chinese cannot be read
  naturally in sequence.

The translation-quality model audit was correctly `SKIPPED` after page
projection failed. These issues came from direct artifact inspection, not the
model audit.

## Review-State Contamination

The newest White House checkpoint contains a `semantic-review-queue.json` whose
`source_run` reports commit `bb6b4be`, 217 subtitles, and the earlier live
artifact directory. The current checkpoint contains 221 subtitles and commit
`6104934`.

The stale queue refers to 15 unique subtitle IDs. For every one of those IDs,
the queue's stored English context differs from the current `subtitle-spans`
English. Nevertheless `subtitle_review_marks.py` reads the queue by ID only and
does not verify the current word-ledger hash, subtitle count, English hash, or
span identity.

This stale queue contributes ten deduplicated yellow tasks. Together with the
seven manually disproved parent-boundary tasks, at least 17/53 yellow tasks
(`32.1%`) have invalid or non-actionable evidence. Therefore the evidence-level
precision ceiling on this run is `67.9%`, even if every remaining yellow task
were useful. The actual overall precision may be lower; an exact value requires
labeling all 53 yellow tasks.

This is a general state-ownership defect. The fix must bind every review source
to at least:

```text
word_ledger_hash + subtitle_id + english_hash + word_start + word_end
```

A mismatched artifact must be rejected or regenerated, never loaded by numeric
ID coincidence.

## Input And Build Reproducibility

### Article input

White House A and the Employment checkpoint contain the identical article-text
hash:

`5da14185a0e544b7775db25f40bedffbe1a5c5ae0c287e0b502ba6f43ba61fc0`

The current UI keeps article text as one panel state and passes that state to
the next media task. It is not keyed by source-media path or source-media hash.
The artifacts prove identical input; the code makes cross-media carry-over
possible. They do not prove whether the user intentionally left that text in
the panel. The safe invariant is still clear: a new media selection must not
silently inherit unconfirmed article input from another media item.

### Runtime code identity

Chocolate `v27` and `v29` have the same word-ledger artifact SHA-256 and the
same internal ledger hash. Both manifests report Git commit `bb6b4be`, but the
planner versions are `v27` and `v29`, and subtitle-span SHA-256 values differ.
Therefore uncommitted runtime code participated in at least one run.

The later `bb6b4be -> 04a8000` commit changed several ownership layers at once:

- `screen_editor.py`: +1,878 / -238 lines;
- `podcast_learning_video.py`: +753 / -59 lines;
- `subtitle_review_marks.py`: +601 / -37 lines;
- `translation_quality_audit.py`: +799 lines;
- `stable_display_page_contract.py`: +134 / -4 lines;
- `subtitle_thread.py`: +262 / -6 lines.

This prevents a reliable line-level claim that one rule caused all observed
changes. Future manifests need a clean/dirty flag plus a deterministic runtime
source digest or build ID. Same-input A/B comparisons must run from committed,
test-verified checkpoints.

## Same-Input Chocolate Evidence

Both runs use ledger hash
`85ba0f98d420cebad931e3c2b068df1dc39c744435085561916af3165710199a`.

- `v27`: 230 parents, 258 pages, `PASS`.
- `v29`: 221 parents, 254 pages, `ERROR`.
- `v29 S0026` merges a 22-word sentence that `v27` represented as two parents;
  the older cut `up | until` was itself linguistically weak, so restoring that
  exact cut is not a valid solution.
- The identical parent text at `v27 S0168` / `v29 S0160` passed in `v27` as
  11+5 words at 56px with a review boundary and at least 1.9 seconds per page.
  `v29` rejects it as having no complete normal-font partition.

This proves two separate defects:

1. Parent segmentation and page feasibility are not stable under the same word
   ledger.
2. A renderable five-word terminal phrase is treated as a structural blocker
   instead of a soft style/review issue.

The six-word preference should remain the default ranking target. It should not
be a hard renderability rule when the terminal page is a complete phrase, fits
at 56px, has sufficient duration, preserves every word, and is objectively
safer than the alternatives.

## Targeted 14-ID Page-Frontier Follow-Up

The follow-up report is
`output/white-house-14-id-frontier-20260823-v2.json`. It uses the immutable
checkpoint `20260823T063436.783343-e950e557` and word-ledger hash
`07a8d2473d53bf5e34b0afbe987f5bbd8528d25015f6fd2f5cb777a469f90ec0`.
This is a targeted page-candidate experiment, not an all-page automation score.

- Eleven of the requested fourteen parents have at least one complete page
  candidate inside their already frozen parent span.
- `S0123`, `S0132`, and `S0192` have no complete normal-font partition under
  the current parent boundary, timing, two-line, and syntax contracts.
- Current production has clear page-boundary defects at `S0037`, `S0051`,
  `S0072`, `S0081`, `S0083`, `S0107`, and `S0201`. `S0110` remains watchable
  review evidence; `S0158`, `S0183`, and `S0206` are usable as displayed.
- The experimental selector changed only `S0081`, replacing four balanced
  pages with a three-page plan containing a 19-word page. Across the eleven
  solvable parents, pages over 16 words increased from three to four, pages
  below 56px from four to five, and high-pressure pages from thirteen to
  fourteen. That selector is therefore not suitable for production.
- The evidence separates two causes: some frozen parents have no legal page
  solution, while other parents have legal candidates but weak ordering. A
  single downstream threshold change cannot repair both classes.

## Cross-Case Conclusions

- Dreamcore shows the basic architecture can produce good results: about
  33/38 difficult parents need no obvious page edit (`86.8%`). It does not
  validate the newer three-stage contracts.
- Japanese X-generation shows that good parent Chinese does not guarantee good
  page Chinese. About 18-21 of 51 multipage parents need review, and `S0136`
  assigns the `50s` number meaning to the wrong page.
- Employment shows geometry errors, missing page Chinese, and real semantic
  findings must remain separate. Its later manual-final success cannot be used
  as the raw automatic score.
- White House B shows both missed true defects and noisy marking in one current
  run. A large yellow count is not merely a stricter but useful audit.
- Provider HTTP 500/timeouts affect completion and latency but do not explain
  deterministic parent boundaries, page partitions, stale marks, or
  mistranslations.

## Mature-Practice Check

Official and maintained sources were rechecked online on 2026-08-23:

- Netflix English (USA): 42 characters per line, at most two lines, adult
  reading speed up to 20 characters/second, and explicit protection of
  article+noun, adjective+noun, name, subject+verb, verb+preposition, and
  auxiliary/negation+verb units.
- Netflix timing: minimum 20 frames (0.8 seconds at 25 fps), with neighboring
  re-segmentation/re-timing encouraged when uneven reading speeds require
  borrowing time.
- TED: over 42 characters should use two lines, never more than two lines,
  preserve linguistic wholes, balance lines, and keep at most 21
  characters/second.
- Subtitle Edit current `TextSplit.cs`: enumerates language-legal split
  candidates, then ranks pixel width and balance; its whole-sentence tools can
  redistribute neighboring subtitles. It remains human-in-the-loop.

Sources:

- https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide
- https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines
- https://www.ted.com/participate/translate/subtitling-tips
- https://github.com/SubtitleEdit/subtitleedit/blob/main/src/libse/Common/TextSplit.cs

These sources support the project's two-line, measured-width, grammar-aware,
human-review design. They do not support treating six words as a universal hard
minimum, nor do they require one monolithic LLM stage. They support considering
neighboring subtitle boundaries before those boundaries become immutable.

## Recommended Implementation Order

### P0: identity and evidence isolation

Owner invariant: every input, cache, audit, checkpoint, and review task must
prove it belongs to the current media, word ledger, English span, and runtime
build.

- Bind article input to media identity and require explicit confirmation before
  carrying it to different media.
- Generate each run in a run-specific staging directory; do not snapshot stale
  media-level QA files.
- Reject semantic/review queues whose ledger/span/English identity differs.
- Add clean/dirty runtime source identity to manifests.

Risk: low. Expected benefit: high for trustworthy review volume and debugging;
it does not directly improve subtitle prose.

### P1: one parser-backed pre-ID boundary gate

Owner invariant: every frozen parent boundary must preserve a legal dependency
unit under the same parser-backed evidence used to enumerate candidates.

- Evaluate complete left+right context for every selected parent boundary, not
  a growing list of token-pair exceptions.
- Repair before IDs freeze; preserve word order, speaker ownership, and timing.
- Make the saved parent-boundary audit consume the exact same decision record,
  so generation and QA cannot disagree.
- Protect the six White House defects and independent negative examples with
  origin-layer tests.

Risk: medium. Expected benefit: high because bad parent cuts poison translation,
page planning, page Chinese, and review quality at once.

### P2: separate renderability from style preference

Owner invariant: hard page failure means lost/reordered words, illegal timing,
pixel overflow, or an inseparable lexical dependency; page density/balance is a
ranking and review concern.

- Keep 6-12 words as the preferred page target.
- Permit a complete, timed, fixed-font terminal page below six words only as a
  recorded `REVIEW` fallback when it dominates every alternative.
- Reproduce Chocolate `S0160` and verify no unrelated White House A page change.

Risk: low-to-medium. Expected benefit: medium-to-high for end-to-end completion.

### P3: validate page Chinese as a continuous viewing sequence

Owner invariant: page Chinese must preserve the parent meaning while matching
the temporal page that owns each fact.

- Bind entities, numbers, negation, comparison halves, and conditions to the
  English page that speaks them.
- Compare adjacent Chinese pages for repetition, premature information,
  dangling grammar, and unnatural continuation.
- Accept a candidate only when it improves a scoped failing parent without
  regressing semantic anchors or reading load.
- Use the stronger translation role only for scoped failures; keep accepted
  parents cached.

Risk: medium. Expected benefit: high for the current weakest long-caption layer;
latency and model cost rise only for failed parents.

### Do not yet add global pre-ID page feasibility

The existing offline joint-planning experiment found zero clearly acceptable
automatic improvements across the four remaining structural targets. Geometry
alone improved two, but one lacked speaker ownership and one produced worse
prose. First fix the parent completeness gate and speaker evidence, then rerun
the same experiment. Implement the joint precheck only if it produces a
positive acceptable-improvement count without changing the passing White House
A replay.

## Acceptance Gates For The 90%-95% Goal

Use exact denominators and separate provider health from content quality:

- healthy-provider runs reaching the editor: `>=95%`;
- actual display pages needing no edit: `>=95%`;
- difficult multipage parents needing no edit: `>=90%`;
- page-Chinese completeness in a formal output: `100%`;
- review-task precision: `>=80%`;
- confirmed-defect recall: `>=90%`;
- parent IDs presented for human review: `<=10%`;
- word coverage/order, frozen ID identity, and final timeline integrity: `100%`.

Every behavior change must be evaluated on a committed same-input A/B build,
the saved recent cases above, and one genuinely unseen audio. A passing manifest
alone is insufficient; the evaluator must score the actual frozen display-page
sequence used by the renderer.
