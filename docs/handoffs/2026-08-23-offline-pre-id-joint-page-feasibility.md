# Offline Pre-ID Joint Page Feasibility

Verified: 2026-08-23 09:50:45 Asia/Shanghai

## Question

Can a bounded move of the two parent boundaries around each difficult White
House subtitle produce a better English parent/page result without changing
word order, word timing, neighboring quality, or an already passing episode?

## Method

- Added `scripts/audit_pre_id_joint_page_feasibility.py`; production code is
  unchanged.
- Read the immutable checkpoint
  `20260823T063436.783343-e950e557`, containing 217 parents and 2,586 words
  under ledger hash
  `07a8d2473d53bf5e34b0afbe987f5bbd8528d25015f6fd2f5cb777a469f90ec0`.
- Tested the 14 requested IDs. For every three-parent window, moved each of
  the two existing cuts by at most eight words while retaining three parents.
- Required the current pre-ID grammar/fragment gate, exact word coverage and
  order, unchanged word timestamps, the 19-word structural ceiling, preserved
  450ms-or-longer boundaries, speaker ownership when available, and a complete
  result from the real 56/54/52px two-line page planner for all three parents.
- Replayed the passing historical White House artifact through the production
  whole-episode candidate selector and final same-screen layout. This guard is
  deliberately not a per-cue replay.
- Made no API request and did not write to subtitles, audio, caches,
  checkpoints, or `work-dir`. The standalone report is
  `output/offline-pre-id-joint-page-feasibility-20260823.json`.

## Results

- Examined boundary combinations: 2,686.
- Feasible changed-boundary alternatives: 1.
- Alternatives that improved the target without worsening either neighbor: 0.
- The only feasible changed alternative was at `S0183`. Moving its first word
  boundary from 2085 to 2089 made the middle parent a clean 12-word page, but
  moved `they can be manipulated,` into the left parent and worsened the
  neighboring window. It is redistribution, not a net improvement.
- `S0123`, `S0132`, and `S0192` remain structurally unpageable and have no
  legal three-parent, same-count alternative within the eight-word radius.
- The other ten tested IDs have no legal changed-boundary alternative. Their
  current issues therefore remain inside-parent page selection problems, not
  evidence that the adjacent formal parent cut should move.
- The historical White House guard passes 217/217 with zero page word-range or
  font-size signature changes.
- The checkpoint contains no usable speaker labels. Speaker-crossing safety is
  enforced by the script when labels exist, but cannot be positively proven
  for this sample.
- Chinese was intentionally not evaluated. A changed parent boundary invalidates
  existing Chinese ownership and requires a fresh translation/allocation A/B.

## Decision

Do not add the proposed same-count, three-parent page-feasibility precheck to
stable mode. It has zero demonstrated net improvements on the requested
targets and therefore does not justify production boundary churn, ID changes,
or translation invalidation.

The evidence separates the next work:

1. Improve page-candidate ordering inside already renderable frozen parents;
   parent boundary movement did not help those targets.
2. If the three structural failures remain worth pursuing, test a higher-risk
   offline planner that may change parent count inside one verified sentence
   or speaker turn. Do not implement it without actual speaker ownership and
   a same-input translation/page-Chinese A/B.

## Approach Comparison

1. Bounded enumeration plus the existing production grammar and page planners
   was selected. The state space is small, the result is explainable, and no
   dependency or duplicate rendering model is introduced.
2. A global shortest-path/dynamic-programming graph could vary parent count
   and optimize a wider sentence window. It may find candidates excluded here,
   but it expands ID, speaker, semantic-group, translation, and cache risk.
3. OR-Tools CP-SAT can represent the same integer constraints and distinguish
   feasible, optimal, and infeasible states. It was rejected for this bounded
   experiment because it adds a dependency and cannot supply missing linguistic
   or speaker evidence.

Current primary-source evidence supports grammar-aware, measured-width,
timing-aware candidate selection, but does not require one monolithic stage:

- Netflix English timed-text guide: 42 characters per line and source-faithful
  segmentation.
  https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide
- Netflix timing guide: timing to audio, minimum duration, and even subtitle
  runs.
  https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines
- Subtitle Edit `TextSplit.cs`: enumerates legal split positions and ranks
  pixel balance; its wider tools can redistribute neighboring subtitles.
  https://github.com/SubtitleEdit/subtitleedit/blob/main/src/libse/Common/TextSplit.cs
- Google OR-Tools CP-SAT: integer constraint feasibility and optimization.
  https://developers.google.com/optimization/cp/cp_solver

## Verification

- `tests/test_pre_id_joint_page_feasibility.py`: 9/9 pass.
- Real experiment: complete in 296.915 seconds.
- Passing White House guard: 217/217, zero signature changes.
- Full regression: 30/30 pass in 904.05 seconds. Repeated `WinError 32` log
  rotation warnings were caused by the running GUI holding `AppData/logs/app.log`;
  they did not cause a test failure.
