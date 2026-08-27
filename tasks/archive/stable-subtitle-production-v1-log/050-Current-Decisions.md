## Current Decisions

- Stable mode should skip old LLM segmentation.
- Stable mode should skip candidate quality check.
- Backchannels should be preserved by default.
- Synthesis should resolve subtitles through `stable-final-manifest.json`.
- Timeline alignment defaults to stable-ts; WhisperX is available as an experimental backend with failure fallback.
- Article-template layout is presentation-only. Its two-line wrapper may
  change visual line breaks but must not recut frozen stable English subtitles.

