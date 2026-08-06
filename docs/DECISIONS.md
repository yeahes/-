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

## 2026-08-04: Boundary Evidence Is Graded, Not POS-Absolute

Decision:

Audit every final English boundary as `hard`, `review`, or `allow`. Only an
atomic structural split with no conflicting word-timing, speaker, or sentence
evidence is `hard`; it must have been repaired before IDs. Ambiguous evidence
is a human review item, not an automatic merge.

Reason:

ASR punctuation and parses are imperfect. Treating a preposition, subordinator,
or finite verb at a cue start as an absolute error would incorrectly merge
independent clauses and speaker turns.

Evidence and trade-off:

Netflix's English timed-text guide requires source-faithful text while using
reading-speed and line constraints; BBC subtitle guidance likewise emphasizes
line/readability constraints. This project adopts their readability principle,
but does not copy broadcast character limits because this is a fixed bilingual
template with an independently tested renderer.

Sources:

- https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-Timed-Text-Style-Guide-General-Requirements
- https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/

## 2026-08-06: Translate Multipage Cues By Display-Page ID

Decision:

Create deterministic display-page IDs only after final word timing. Translate
each multipage span by its exact child ID, validate the complete child-ID set,
then aggregate Chinese back into the unchanged parent subtitle.

Reason:

Parent-level Chinese may reorder English clauses naturally. Dividing that
Chinese string by English word proportions can therefore place correct meaning
on the wrong timed page even when the parent subtitle is semantically valid.

Rejected:

- Proportional Chinese character slicing.
- Letting the renderer rewrite parent English, IDs, cue timing, or SRT/ASS.
- Silently shrinking fixed fonts or accepting a stale page artifact.

Trade-off:

Multipage cues add one cacheable LLM allocation stage after final alignment.
This costs latency on cache misses but gives page semantics an explicit,
auditable owner and allows synthesis to fail before ffmpeg on contract drift.
