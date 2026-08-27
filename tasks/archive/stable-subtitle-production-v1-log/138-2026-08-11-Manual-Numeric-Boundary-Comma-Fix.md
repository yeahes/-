## 2026-08-11 Manual Numeric Boundary Comma Fix

- Reproduced the manual boundary false positive where moving `the` from
  `In the 12 months prior to early 2026, the` caused the numeric fallback to
  absorb `2026,` as well.
- The manual expansion guard now recognizes trailing comma, semicolon, and
  colon as completed clause boundaries. True numeric units and magnitudes
  remain atomic, while a following article can move independently.
- Added a regression for `2026, / the` and retained the existing `740 billion`
  bidirectional protection test. The manual-editor script and the complete
  25-stage unified regression pass.

