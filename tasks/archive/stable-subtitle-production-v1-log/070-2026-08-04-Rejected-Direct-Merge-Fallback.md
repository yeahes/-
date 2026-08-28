## 2026-08-04 Rejected Direct Merge Fallback

- Root cause: after a direct weak-fragment merge was rejected by the candidate
  gate, the pre-ID repair loop skipped the normal safe-repartition search for
  that same local window. This left a legal repair untried, as in the
  `Yeah, so Todd` subject-fragment regression.
- A rejected direct merge now falls through to the existing local repartition
  candidates. The successful candidate must still pass the shared word-order,
  word-range, speaker, syntax, fragment, and word-limit gate before writeback.
- The regression now asserts the selected frozen word spans `(0, 8)` and
  `(9, 14)`. No post-ID English, Chinese, timing, or synthesis behavior is
  changed.
- `runtime\python.exe -X utf8 tests\test_stable_caption_rules.py` and
  `runtime\python.exe -X utf8 scripts\run_regression.py` passed.

