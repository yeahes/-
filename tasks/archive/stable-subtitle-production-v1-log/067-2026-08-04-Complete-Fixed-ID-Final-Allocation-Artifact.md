## 2026-08-04 Complete Fixed-ID Final Allocation Artifact

- Root cause: `allocation-final.json` was assembled only from allocation
  attempts accepted by the quality gate. When a retry remained unresolved, the
  final subtitle writeback retained an ID-bound Chinese value but the final
  allocation artifact omitted that group's IDs.
- The artifact now derives every group mapping from the final fixed-ID subtitle
  items used for export. Existing accepted-attempt provenance is retained when
  it still matches; otherwise the record explicitly identifies final-item or
  unresolved-final-item provenance. `allocation-unresolved.json` remains the
  sole record of why a quality issue was not resolved.
- English text/order, subtitle IDs, word ranges, timings, allocation decisions,
  and render gating are unchanged.
- Added a regression case for an unresolved group whose retained Chinese must
  still appear in the final allocation artifact.

