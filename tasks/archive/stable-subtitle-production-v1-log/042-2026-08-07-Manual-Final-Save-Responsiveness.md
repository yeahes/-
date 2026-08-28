## 2026-08-07 Manual-Final Save Responsiveness

- A production GUI save of the 203-cue `中国AI为何更省钱？` failure checkpoint
  blocked the Qt event loop for about three minutes. The save did complete and
  publish a fail-closed manual package; no subtitle data was lost.
- Root cause profiling attributes 188.384 of 188.806 seconds to deterministic
  page-blueprint construction, dominated by 690,471 font-width measurements.
  SRT and JSON writes together were below half a second.
- The editor now deep-copies the synchronized manual session, disables editing
  and manual-final actions, and performs the unchanged package/page validation
  in a background worker. A Qt signal applies the result on the GUI thread;
  thread-start failures restore the controls, concurrent saves are serialized,
  and application exit is blocked until publication finishes.
- Focused publication regression and targeted `git diff --check` pass. The
  delegated real-checkpoint replay terminated normally, kept the expected
  `manual_page_translation_required` gate, made zero external/ASR/LLM/FFmpeg
  calls, and did not modify the production source checkpoint.
- Evidence:
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-manual-save-profile-20260807-r2`.

