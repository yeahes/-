## 2026-08-20 Display-Page Failure Isolation And Editor Retry Context

- Audited the saved Dreamcore failure before editing. One six-parent batch
  returned no usable page rows, but the request loop marked it complete; a
  later retry then expanded the visible failure from six parents to all 37.
- The page validator now retains independently complete parents while keeping
  the full artifact blocked. Identifiable structural errors retry only their
  owning parent IDs; the full merged contract must still pass before writeback.
- Failed page previews display the complete parent Chinese only once as an
  unconfirmed reference. Empty later pages remain explicit manual work.
- Retrying the same subtitle in the editor now preserves source audio, article
  context and switches, output mode, and manual-review state. Cross-file imports
  remain isolated.
- Focused suites and the complete 26-stage offline regression pass. No English
  segmentation, page scoring, font, timing, synthesis, paid request, or
  production artifact changed. The user chose to leave `4 | chan` to manual
  page-boundary editing.

