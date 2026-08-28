## 2026-08-08 Audio-Folder SRT Package Recovery

- Reproduced the GUI failure from the application log: synthesis selected
  `C:\Users\19379\Desktop\中国AI为何更省钱？\中国AI为何更省钱？-原文在上双语字幕.srt`
  directly, so the article renderer had no adjacent final timeline or word
  ledger and raised `missing_or_mismatched_word_ledger` before FFmpeg.
- The same detached SRT also explained why importing it into the subtitle
  editor left `合成草稿` disabled: manifest discovery previously compared paths
  only and could not reconnect a renamed byte-for-byte copy.
- Manifest discovery now accepts only exact path or SHA-256 identity, prefers
  a saved manual package over an older hash-identical checkpoint, and restores
  editor/synthesis draft state only after the existing package hash gates pass.
- Manual save publishes and records a media-named SRT; saving that source copy
  uses a media-named portable package. Normal stable success also writes the
  media-named SRT. No English, Chinese,
  cue ID, word span, cue time, page-planning rule, or renderer style changed.

