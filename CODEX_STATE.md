# Project State

Status: complete
Last verified: 2026-08-26 01:36:35 Asia/Shanghai
Branch: main
Verified HEAD: f00edc4
Working tree: modified (recent-recovery source/tests plus pre-existing unrelated changes)

## Current Goal
Restore the newest saved manual-final subtitles after restart without rerunning ASR, translation, or pagination.

## Confirmed Facts
- Recovery follows hash-verified `source_subtitle_paths` and `paths` from stable manifests to the owning `*-处理结果/人工终稿字幕包`.
- Results are grouped by owning result directory, preventing derived media names or same-name media in other directories from being merged incorrectly.
- Selection is ordered by real update time; a newer final supersedes an older draft, while a genuinely newer draft remains recoverable.
- The real `拆解白宫所谓的中国转运骗局` manual package loaded directly with 199 cues and no pipeline or API call.
- Focused manual-editor tests pass 136/136. Full regression passes 31/32; the remaining article-readability fixture is unrelated.

## Approved Decisions
- Do not rerun or mutate manually reviewed audio packages for recovery verification.

## Relevant Paths
- Source: `app/core/subtitle_processor/manual_final_subtitle_editor.py`
- Tests: `tests/test_manual_final_subtitle_editor.py`
- State: `docs/CURRENT_STATE.md`

## Last Verification
- Real manual-final manifest discovery and load: 199 cues, state `人工终稿`.
- `runtime\\python.exe -m pytest tests\\test_manual_final_subtitle_editor.py -q`: 136 passed.
- `runtime\\python.exe scripts\\run_regression.py`: 31/32; one unrelated existing readability failure.

## Next Action
Restart the application and use `恢复最近字幕` for the newest manual final; then return to the mainline subtitle-quality work.

## Do Not Regress
- Preserve manifest hash validation, frozen English/IDs/timing, draft recovery, and no writes to `D:\\软件缓存\\VideoCaptioner`.

## Unknowns
- Live GUI selection after an application restart has not yet been user-confirmed.
