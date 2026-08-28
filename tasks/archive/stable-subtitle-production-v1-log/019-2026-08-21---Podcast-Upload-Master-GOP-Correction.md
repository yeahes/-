## 2026-08-21 - Podcast Upload Master GOP Correction

- Confirmed the two 13:21 employment outputs were 2560x1440 upload masters at
  7.17-7.53 Mbps and 684.55-718.78 MB; the saved resolution option was 1440p.
- Corrected the fixed GOP from 13 frames (0.52 seconds) to 50 frames (2 seconds)
  at 25 fps. CRF 15 and the existing quality settings remain unchanged.
- Command regression coverage locks both `-g` and `-keyint_min` to 50 and keeps
  scene-cut insertion disabled for deterministic cadence.
- Two representative 20-second re-encodes measured 4.47/4.58 MiB at 1080p and
  5.85/5.99 MiB at 1440p. For the same 13:21 bilingual video, those samples
  extrapolate to about 181 MiB and 237 MiB. Samples are stored under
  `output/encoding-size-check-20260821/`.

