## 2026-08-04 Stable Manifest Authority

- Root cause: a malformed or unusable `stable-final-manifest.json` was caught
  and ignored by podcast-template subtitle resolution. The resolver then used
  filename-based discovery, which could select a stale SRT in the same folder.
- Fix: an existing manifest is authoritative. Decode, schema, and declared
  final-SRT failures now stop synthesis; filename discovery remains available
  only when no manifest exists. Manual-final override and legacy
  reading-speed revalidation retain their existing manifest-bound behavior.
- Added regression coverage for malformed manifests and missing manifest SRTs
  in a folder containing a stale candidate.

