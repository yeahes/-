## 2026-08-25 - Manual-final save accepts current page state after parent merges

- Reproduced the failed Japanese X-generation save from its recovery draft.
  The current draft had valid manual pages for `S0001` and `S0242`, while the
  source artifact still carried orphan plans for merged-away `S0003` and
  `S0109`.
- The save contract now skips only history-proven, unreferenced orphan plans;
  current page edits and boundary overrides still require exact identity checks.
  A manual override also clears the stale geometry-only blueprint error from
  the page confirmation projection.
- Added regressions for cross-parent merge save and manual confirmation after
  an old blueprint failure. Background exceptions now return structured error
  codes and page positions instead of an unknown UI warning.
- Focused verification: `tests/test_manual_final_subtitle_editor.py` passed
  132/132. A full regression and a post-restart real save remain to be checked.

