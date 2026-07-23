# Decisions

## 2026-07-22: English Segmentation Remains Local

Decision:

Stable mode performs English subtitle segmentation locally from word-level timestamps.

Reason:

Allowing an LLM to segment English caused unstable line lengths, occasional reordering, and missing coverage.

Rejected:

LLM jointly segments English and translates Chinese.

Reconsider only if:

A new method passes token coverage, order, timing, and rendering regression tests.

## 2026-07-22: Preserve Backchannels By Default

Decision:

Spoken backchannels such as `Right`, `Yeah`, and `Exactly` are preserved by default.

Reason:

Deleting them reduced token cost and visual clutter but created a higher risk of audio with no displayed English.

Rejected:

Global deletion of pure backchannels.

## 2026-07-23: Stable Final Manifest Controls Video Synthesis

Decision:

Video synthesis should prefer `stable-final-manifest.json` and its `original_top_srt` path.

Reason:

Localized file-name search can select stale SRT/ASS outputs. This caused code fixes to not appear in rendered videos.

Rejected:

Selecting subtitle files by broad `*-原文在上.srt` search when a stable manifest exists.

## 2026-07-23: Candidate Quality Check Disabled In Stable Mode

Decision:

Candidate quality check is bypassed when stable mode is enabled.

Reason:

It gives the LLM another chance to change subtitle structure after deterministic cutting.

Rejected:

Running a second LLM correction pass in the stable production path.
