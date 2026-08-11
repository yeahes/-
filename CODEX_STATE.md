# Project State
Status: complete
Last verified: 2026-08-11 11:28:22 Asia/Shanghai
Branch: main
Verified HEAD: 384ec86d64fe07d17a0f7a12d421e751c316acbf
Working tree: modified by earlier editor/render changes plus current ASR and timing-trust repair

## Current Goal
Recover high-confidence internal ASR omissions and prevent compressed aligner word times from reaching the frozen final timeline.

## Confirmed Facts
- Faster Whisper skipped 23 spoken words around 08:51; a bounded context-free retranscription recovered them between exact anchors.
- Stable-ts compressed six words near subtitle 281 into 120ms, leaving the eight-word cue with a 741ms envelope.
- A 99-ledger audit found no credible legal-speed false positive at the retained detector thresholds; old overlapping-window merging could expand one repair to 40 words.
- Current detection selects the minimum anomaly core and timing fallback expands only words inside the same collapsed envelope before detecting again.

## Approved Decisions
- Repair omissions before English boundaries and IDs freeze; require audio activity and exact anchors on both sides.
- Restore implausible stable-ts or WhisperX updates only from a timing-trusted upstream ledger; otherwise fail closed.

## Relevant Paths
- `app/core/bk_asr/faster_whisper.py`
- `app/core/subtitle_processor/word_timing_trust.py`
- `app/core/subtitle_processor/stable_ts_alignment.py`
- `app/core/subtitle_processor/final_cue_timeline.py`
- `tests/test_asr_trust_contract.py`

## Last Verification
- ASR trust 33/33, final timeline pass, complete stable-caption rules pass, syntax compilation pass, and all 25 unified regression stages pass in 362.2 seconds.

## Next Action
Restart the GUI and run one fresh audio workflow so new ASR and alignment output is generated instead of reusing the old production subtitle package.

## Do Not Regress
- Do not alter frozen English, IDs, word order, Chinese allocation, pagination, or rendering to hide an ASR/timing defect.

## Unknowns
- A fresh full production rerun has not yet been made with both repairs enabled.
