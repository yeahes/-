## 2026-08-06 56px Visual Budget and Manual-Final Checkpoint

- Changed the article English default from 58px to 56px and made the 16-word
  visual-page limit a planning penalty instead of a feasibility gate. Grammar,
  measured pixels, and minimum page duration remain higher-priority evidence.
- Added a recorded 54/52/50/48/46px fallback sequence for cues that have no safe
  higher-size plan. Font fallback cannot mutate frozen cue IDs, text, spans,
  timing, or Chinese allocation.
- Reduced editor noise by consuming the completed English boundary audit and
  surfacing only high-confidence English/Chinese, cue-edge timing fallback, and
  high-risk page-boundary evidence.
- Editor saves now publish a separate, hash-bound `人工终稿字幕包/`. Valid packages
  carry their source-media path and can be imported directly by the synthesis
  page; unresolved page-level Chinese mappings save as blocked checkpoints, so
  upstream ASR/translation work does not need to be repeated.
- Focused manual-final and synthesis-safety tests pass. No external request or
  synthesis ran.
- Bumped the page planner contract to `article-fixed-font-pages-v6`. A verified
  pause of at least 600ms may downgrade only clause-level subject/predicate or
  `that` + `-ing` page boundaries to high-confidence review; lexical phrase
  boundaries remain hard. This resolves the 28-word `S0120` case through its
  actual 901ms and 800ms pauses rather than a text-specific exception or a
  smaller font.
- Final v6 offline replay under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-e2e-20260806-page-contract-r10-offline-audit`
  plans 262/262 cues with zero failures. Font distribution is 56=242, 54=2,
  52=8, 50=5, 48=1, and 46=4. Twenty-one pages exceed the soft 16-word budget;
  selected boundary review is high=3, medium=8, acceptable=11, and none of the
  10 known bad cuts remains.
- `S0120` now uses three 56px pages split after `sources,` and at the verified
  800ms `gear | is` pause. No frozen cue, text, ID, Chinese mapping, or timing
  changed. Unified regression and representative transition-frame validation
  remain pending.

