# Offline Joint Planning Comparison

Verified: 2026-08-22 20:38 Asia/Shanghai

## Question

Does running authoritative display-page feasibility before English subtitle ID
freeze demonstrate enough net benefit to justify a production change?

## Method

- Replayed saved word ledgers, word timings, parent Chinese, and frozen boundary
  evidence with baseline commit `04a8000`.
- Made no API call, GUI run, production-code change, or work-dir artifact write.
- Replayed all 217 White House parents at their existing boundaries.
- For six three-parent windows, enumerated every ordered pair of boundary shifts
  within eight words of the saved cuts.
- Accepted a candidate only when it preserved complete word coverage, passed the
  current pre-ID boundary and fragment gates, stayed within the 19-word parent
  limit, and produced a real 56/54/52px two-line/timing-valid page plan for
  every resulting parent.
- The generated diagnostic and raw result remain under
  `output/offline-joint-planning-comparison-20260822/` and are not committed.

## Results

### Passing Counterexample

- White House replay: 217/217 parents renderable.
- Page count changes: 0/217.
- This proves the current page planner can preserve this passing fixed-boundary
  sample. It does not prove that moving pre-ID boundaries is safe.

### Previously Reported Failures

| Target | Current baseline replay | Geometrically feasible local alternatives | Interpretation |
| --- | --- | ---: | --- |
| Chocolate `S0026` | still fails | 0/187 combinations | local joint planning did not solve it |
| Chocolate `S0160` | still fails | 6/288 combinations | candidates move `Wow.` or `It is.` across parent boundaries; speaker ownership is unavailable |
| Employment `S0029` | passes at 56px | 0/266 combinations needed | old v28 artifact failure; no joint planning required |
| Employment `S0223` | still fails | 0/169 combinations | local joint planning did not solve it |
| Employment `S0247` | still fails | 2/272 combinations | both candidates strand `And eventually,` on the previous parent and are not acceptable prose |
| Japanese `S0136` | still produces the same two pages | 0/182 combinations | page-Chinese/number-anchor ownership, not a parent-cut solution |

After removing the already-fixed `S0029` and the independent page-Chinese
`S0136` case, the structural denominator is four targets:

- Geometry-only improvement: 2/4.
- Clearly acceptable automatic improvement: 0/4 proven.
- Potentially acceptable with missing speaker evidence: at most 1/4 (`S0160`).
- Unsolved: 2/4 (`S0026`, `S0223`).
- Geometry-valid but linguistically worse: 1/4 (`S0247`).

## Conclusion

The experiment does not demonstrate positive net benefit for the proposed
minimal production change. Reusing the existing page planner before ID freeze
would solve some pixel-fit states, but the current pre-ID completeness gate can
still accept a visibly stranded transition. It also lacks speaker evidence
needed to move short reactions safely.

Do not implement the joint gate yet. The next owner problem is narrower:

1. Make parent-boundary validation reject complete-looking parents that end in
   an unfinished transition belonging to the following clause.
2. Preserve or reconstruct speaker-turn evidence before moving reactions such
   as `Wow.` and `It is.`.
3. Re-run the same comparison. Only implement pre-ID page feasibility if the
   acceptable-improvement count becomes positive without a White House
   regression.

## Limits

- The search kept the same number of parents and used only each target plus its
  immediate left and right parent. A wider/global search may find more geometry
  solutions, but it also expands ID, translation, and semantic ownership risk.
- No unseen audio was used, so this experiment cannot establish a population
  success percentage.
