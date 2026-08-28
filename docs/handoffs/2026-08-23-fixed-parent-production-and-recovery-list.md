# Fixed-Parent Production Selection And Recovery List

Verified: 2026-08-23 Asia/Shanghai

## Production Page Selection

The fixed-parent material-readability selector is now the final production
selection pass in article planner v32. It uses only candidates already created
by the deterministic renderer. A candidate must materially reduce a short
page, over-16-word load, font deficit, or maximum display pressure while adding
no unsupported REVIEW edge, short fragment, font/line regression, imbalance,
or structural risk.

It cannot change parent English, subtitle IDs, word ranges, word timestamps,
cue timing, or parent Chinese. Its reason is persisted in the render plan.

Newest White House read-only replay:

- compared render plans: 217/217
- changed IDs: `S0072`, `S0097`, `S0201`, `S0205`
- unexpected changes: zero
- retained structural blockers: `S0123`, `S0132`, `S0192`
- API requests and artifact writes: zero

The prior bilingual experiment validated all four changed page-Chinese sets in
one request. Historical White House, Chocolate v27/v29, and Employment guards
had zero material changes under the same selector.

The approach follows the existing local candidate-enumeration architecture.
Netflix's current English and timing guides and Subtitle Edit's maintained
`TextSplit.cs` were revalidated online on 2026-08-23; all three sources were
available. They support source-faithful, timing-aware, readable split ranking,
but do not replace this project's fixed-ID bilingual contracts.

## Recovery Workflow

Recent-result discovery now:

- deduplicates live aliases of one run;
- collapses historical runs to one entry per audio title;
- preserves an unsaved draft ahead of clean history;
- otherwise selects the newest result;
- checks the deterministic source-adjacent manual-final package; and
- shows its exact destination in the themed restore dialog.

For the current White House source audio, the user-facing destination is:

```text
C:/Users/19379/Desktop/白宫对中国转运骗局的荒谬指控/
  白宫对中国转运骗局的荒谬指控-处理结果/人工终稿字幕包/
```

The root `stable-final-manifest.json` points to immutable generations below
that directory. Restoring it does not run ASR, translation, allocation, or
pagination.

## Verification Boundary

Focused tests, syntax checks, real recovery discovery, and the real White House
read-only plan comparison are owned by this stage. The user explicitly owns
the complete `scripts/run_regression.py` run. The focused selector, editor,
and publication set finished with `223 passed`; real recovery discovery
returned 20 episode entries in 0.367 seconds and collapsed the five newest
White House histories into one entry.
