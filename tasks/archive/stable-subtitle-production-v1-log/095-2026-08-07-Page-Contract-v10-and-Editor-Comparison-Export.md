## 2026-08-07 Page Contract v10 and Editor-Comparison Export

- Eight real 203-cue items could not satisfy the strict v9 page partition at
  50px or larger. V10 exhausts strict candidates first, supports at most four
  pages, and only then permits a complete continuation phrase/clause as a
  high-risk reviewed display boundary. Frozen parent IDs, English, word spans,
  timing, and word timestamps remain unchanged.
- Fixed dynamic-program risk propagation, published every render plan and the
  complete word-ledger-bound display-boundary evidence, and added planning
  memoization. The eight hardest fixture cues now plan in 71.631 seconds versus
  about 142 seconds before caching.
- Manual-final publication exports a page-level bilingual SRT plus exact page
  map. A missing/invalid page translation remains render-blocked and editable;
  no raw Chinese character slicing or silent font reduction is used.
- Fresh E2E under
  `E:\VideoCaptioner-e2e-runs\china-ai-cheaper-page-contract-v10-e2e-20260807-r1`
  produced 203 parent cues, 2,548 words, 252 pages, 49 transitions, and 38
  multipage parents. Minimum English font is 50px and minimum timed-page
  duration is 1,051ms. Final timing is `PASS` with
  `applied_backend=whisperx-time-only`, no `source_audio_missing`, and no
  overall backend fallback.
- External requests were 15: ten full-translation batches, three normal
  fixed-ID allocations, one fragment retry, and one page-translation request.
  No external ASR request or video synthesis ran.
- The older 16:36 checkpoint was rejected as an exact baseline because it
  omitted or rewrote four source words that are present in the shared input
  SRT. The current result instead passes its internal frozen ID/ledger/timeline
  contracts.
- Independent validation passed all 252 exported SRT/map pages and 2,548 word
  IDs. Forty-seven rendered midpoint and transition frames across the eight
  former hard cues had zero blank, crop, or bilingual overlap failures. Nine
  English page-boundary reviews and one S0202 Chinese continuation review remain
  visible for human judgment.

