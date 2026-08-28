## 2026-08-12 Pre-ID Overlong Contract Consistency

- Replayed the failed `好莱坞最新热潮：姐弟恋` artifacts. `S0020` had a
  correct `[243, 244]` sentence boundary after `_stable_cut_items`, but the
  final adjacent-window rebalancer removed it as `short_dependent_tail_merged`.
  `S0267` had a 15/4-word candidate that the formal pre-ID gate rejected as
  `short_open_prefix_fragment`, while final validation ignored that rejection.
- Over-limit adjacent-tail merges now require the existing shared
  structural-overflow proof. Final validation now evaluates a proposed split
  with its adjacent frozen cues through `_can_apply_pre_id_repair_candidate`.
  These changes unify the planner and release gate without changing the
  16-word limit or adding text-specific exceptions.
- Added regressions for `... exact dynamic. / Lots of money.` and the complete
  `If modern relationships ... lifelong partnerships,` clause. Existing
  dependent-tail merge and structural-overflow tests remain green.
- Production-ledger replay retains the 15/3-word sentence split and reduces
  hard `overlong_english` findings from two to zero. The complete stable
  caption script passes in 91.1 seconds; all 25 unified regression stages pass
  in 368.1 seconds. External requests and production writes are zero.

