# Independent Diagnostic Brief: Stable Subtitle Pipeline

**Generated:** 2026-08-22 18:59:36 Asia/Shanghai
**Purpose:** hand this file to a fresh, isolated agent for a root-cause audit.
**Important:** this is an evidence index, not an instruction to accept the current
agent's conclusions.

## 1. Audit Rules For The Fresh Agent

Start from the artifact files listed below. Do not start from old chat conclusions.
Separate every statement into:

- **Observed fact:** directly present in code, manifest, artifact, test output, or
  reproducible command output.
- **Hypothesis:** a possible explanation that still needs a reproduction.
- **Decision:** a user-approved invariant that must not be changed casually.

Before proposing a code change, answer all of these:

1. Where was the defect first created: ASR, article correction, English parent
   segmentation, parent Chinese translation, fixed-ID allocation, timing, page
   planning, page-Chinese projection, review classification, save/reload, or
   synthesis selection?
2. Can the defect be reproduced from the saved artifact without calling an API?
3. Is the reported issue a real output defect, a false review mark, a provider
   failure, or an artifact/state mismatch?
4. Does the same failure appear in at least two unrelated audio titles? If not,
   treat it as a boundary case until proven general.
5. Does the proposed fix preserve English text/order, fixed IDs, word ownership,
   word timing, parent Chinese authority, page IDs, and synthesis input identity?

Do not add a title-specific or subtitle-ID-specific rule. If two consecutive
changes do not improve a held-out sample, stop coding and re-audit the hypothesis.

## 2. Project Goal And Hard Contracts

The project converts English podcast audio into a static educational video:

```text
audio
  -> ASR transcript and word timestamps
  -> article-assisted ASR correction (optional, source-evidence constrained)
  -> local deterministic English parent segmentation
  -> freeze parent subtitle IDs and word spans
  -> complete semantic-group Chinese translation
  -> Chinese allocation to exact frozen parent IDs
  -> final word-ledger timing and cue timeline validation
  -> deterministic display-page planning inside each frozen parent cue
  -> Chinese projection to exact Sxxxx.Pxx page IDs
  -> review ledger / manual final save
  -> synthesis resolves the frozen stable-final-manifest.json
```

Non-negotiable contracts:

- Stable English text, order, timing ownership, and IDs are local and
  deterministic. An LLM must not decide final English segmentation.
- The authoritative word ledger is the only final timing authority.
- Parent Chinese is translated as a complete semantic group, then mapped back to
  fixed English IDs. A missing or invalid fixed-ID record must stop before the
  authority artifact is written.
- Display pagination can split only a frozen parent word span. It cannot change
  parent English, parent ID, word ownership, cue timing, or parent Chinese.
- Page Chinese is a display-only projection of authoritative parent Chinese. It
  must use exact page IDs and cannot invent, duplicate, or move meaning across
  pages.
- The editor, manual-final save, and video synthesis must consume the same frozen
  page plan and manifest. A blocked manifest must not synthesize.

### Word-count terminology

These are intentionally different limits:

- **6-12 words:** preferred visual density for an English parent/page.
- **14 words:** comfortable display-page target used by page planning.
- **16 words:** normal English parent hard limit and page soft pressure limit.
- **17-19 words:** only an audited grammar-preserving exception when every normal
  cut creates an incomplete or unsafe unit.

Do not treat 16 as the visual ideal or 14 as the current universal hard limit.

## 3. Main Code Ownership

- `app/thread/subtitle_thread.py`: orchestration, stage progress, checkpoints,
  manifest creation, failure ownership, and quality-audit scheduling.
- `app/core/subtitle_processor/screen_editor.py`: stable English boundaries,
  semantic translation/allocation, timing preparation, page-translation requests,
  and artifact construction. This is highly coupled and high risk.
- `app/core/subtitle_processor/stable_display_page_contract.py`: page IDs,
  page schema, contract hash, response cardinality and page authority checks.
- `app/core/utils/podcast_learning_video.py`: measured fixed-font page planning
  and rendering. Current planner constant is `article-fixed-font-pages-v29`.
- `app/core/subtitle_processor/subtitle_review_marks.py`: converts validation,
  page, ASR, Chinese, and model-audit evidence into editor tasks.
- `app/core/subtitle_processor/manual_final_subtitle_editor.py`: loads editable
  checkpoints/manual finals and publishes a validated generation.
- `app/thread/video_synthesis_thread.py`: resolves the stable manifest and blocks
  synthesis when `render_blocked` is true.

Relevant local documents:

- `docs/PROJECT_OVERVIEW.md`
- `docs/ARCHITECTURE.md`
- `docs/PIPELINE.md`
- `docs/SUBTITLE_RULES.md`
- `docs/CURRENT_STATE.md`
- `docs/handoffs/2026-08-22-subtitle-segmentation-translation-pagination-context.md`
- `tasks/active/stable-subtitle-production-v1-log.md`

## 4. Artifact Identity Warning

The current worktree is dirty and has not been committed. `git HEAD` is
`bb6b4be8a88ab013d0275609c81ef5c539d2a478`, branch `main`; `git status --short`
shows roughly 40 modified files and several untracked files. Existing manifests
record only that clean HEAD as `code_commit`; they do **not** prove that the
working-tree source used for each run was identical.

Therefore, do not infer “version v29 caused the failure” solely from a manifest.
Planner/prompt versions, API model, cache use, source artifact hash, run time,
and the actual current diff must be compared. This missing dirty-worktree
fingerprint is itself a reproducibility defect.

## 5. Case Evidence

All paths below are under the working copy and are original generated artifacts,
not GUI screenshots. The fresh agent should inspect each run's:

- `stable-final-manifest.json`
- `...-artifacts/editor-review-ledger.json`
- `...-artifacts/display-page-translations.json`
- `...-artifacts/authoritative-parent-chinese.json`
- `...-artifacts/display-boundary-evidence.json`
- `...-artifacts/translation-quality-audit.json`
- `...-artifacts/translation-structure-errors.json`

### A. White House: post-three-stage passing baseline

Title: `白宫对中国转运骗局的荒谬指控`
Run:
`work-dir/白宫对中国转运骗局的荒谬指控/subtitle/stable-runs/20260821T230939.708705-4e6f51c9`

Observed manifest facts:

- 217 fixed parent IDs; validation `passed`; `render_blocked=false`.
- Page translation `PASS`; planner `article-fixed-font-pages-v29`.
- 16 editor tasks, all `REVIEW`, no blocker.
- 30 structural English-overflow warnings: complete sentences above 16 words
  with no parser-confirmed safe internal cut.
- 14 suspicious-cut warnings, 37 English-boundary review warnings, 9 Chinese
  semantic-group warnings, 2 ASR-suspicious warnings.
- Translation-quality audit: 4 candidate findings, no batch/verification error.
- Stage times: article correction 13.1s, alignment 54.4s, page translation
  247.0s, screen subtitle edit 574.7s.

Representative task types:

- Page boundary review: `arguments | coming`, `understand | why`,
  `paper, | which`, `goods | coming`, `cargo | from`, `prove | that`.
- Chinese semantic review: `S0081`, `S0085`, `S0190`.
- ASR review: `S0087` (`change/changes`), `S0216` (`terrorists/tariffs`).

Audit question: are the 16 tasks useful high-value review, or are the page
boundary marks over-reporting watchable but legal continuation boundaries?

### B. Chocolate old title: failed original run

Title: `中国会有爱上巧克力的一天吗？`
Latest failed run:
`work-dir/中国会有爱上巧克力的一天吗？/subtitle/stable-checkpoints/20260822T013841.567135-4734ae40`

Observed facts:

- 221 parent records; validation `failed`; `render_blocked=true`;
  display-page status `ERROR`.
- Four page errors: missing `S0220.P01/P02`, cardinality mismatch (expected 63,
  returned 61), and no complete normal-font partition for `S0026` and `S0160`.
- 45 editor tasks, 3 blockers. The queue also contains English boundary reviews,
  visual boundary reviews, translation/semantic findings, and ASR review.
- Important semantic examples: `S0059` (98% meaning reversed), `S0062` (missing
  “enter/fill the gap”), `S0063` (`stringing/springing`), `S0127` (missing
  “the why behind”), `S0136` (“双刃剑” word order), `S0188/S0196` longan term
  inconsistency, `S0205` missing “incoming disruption”.
- This title also has an earlier passing v27 run:
  `stable-runs/20260821T095357.545965-d8d99059`, with 230 parent records,
  page `PASS`, and 13 tasks. The two outputs must not be treated as the same
  artifact or as proof that one code rule alone caused the difference.

Audit question: separate deterministic planner failures (`S0026`, `S0160`),
page-response completeness (`S0220`), model/API variability, and true parent
translation defects. Do not combine them into “pagination is bad”.

### C. Chocolate new title: provider failure plus shared planner failures

Title: `中国人会爱上巧克力吗？`
Run:
`work-dir/中国人会爱上巧克力吗？/subtitle/stable-checkpoints/20260822T055458.909586-5acb15d6`

Observed facts:

- 221 parent records; validation `failed`; `render_blocked=true`;
  display-page status `ERROR`.
- Planner errors for `S0026` and `S0160`, the same parent IDs seen in the old
  Chocolate title.
- Page translation batch 3/6 failed with provider HTTP 500 for parents
  `S0054,S0058,S0062,S0066,S0082`; the persisted error owns 19 affected page
  parents. This is a provider failure, not evidence that all 19 pages are bad.
- Editor ledger has 60 tasks, 21 blockers. The large blocker count is inflated by
  the failed batch; it must not be used as a pure subtitle-quality score.
- Translation-quality audit has zero findings because it was correctly skipped
  after the page-stage failure; it has one batch error.

Audit question: confirm that failed external requests are isolated from page
quality findings, that completed page batches remain reusable, and that a retry
does not turn one provider failure into 19 stale permanent blockers.

### D. Employment: structural page pressure plus real Chinese findings

Title: `无论怎么衡量，就业市场都很疲软`
Raw checkpoint:
`work-dir/无论怎么衡量，就业市场都很疲软/subtitle/stable-checkpoints/20260821T145313.192574-4fbdb7bc`

Observed facts:

- 260 fixed parent records; raw checkpoint validation `failed` and blocked.
- Planner `article-fixed-font-pages-v28` reported:
  - missing page IDs for `S0016` and `S0123`;
  - `S0029` and `S0223` no normal-font partition;
  - `S0061` cue duration below page minimum;
  - `S0247` no normal-font partition.
- The editor groups `S0016,S0029,S0061,S0123,S0223,S0247` into one blocker task.
- Real Chinese mapping findings include `S0015/S0016` yardstick/goalpost drift and
  `S0057` modifier-to-head mismatch. Other findings are omitted discourse markers
  (`Exactly`, `Yeah`, `Right`) and page-Chinese continuity warnings.
- `S0204.P02` is 29 Chinese characters versus the suggested 28-character budget.
- ASR findings include `S0089` (“one at home 15 months” vs 115 months) and `S0253`
  (“ditness trackers” vs fitness trackers).
- A later manual-final publication exists in project history and is a separate
  human-edited artifact. Do not use the raw blocked checkpoint as proof that the
  published manual final was unusable.

Audit question: classify each task as parent translation, page projection,
English ASR, page geometry, or false-positive discourse-marker review. Check
whether the six-ID blocker is incorrectly collapsing independent causes.

### E. Japanese X-generation: newest held-out failure

Title: `日本X世代的困境：被反复诅咒的一代人`
Run:
`work-dir/日本X世代的困境：被反复诅咒的一代人/subtitle/stable-checkpoints/20260822T081526.304594-8536fe61`

Observed facts:

- 241 parent records; validation `failed`; `render_blocked=true`.
- One page semantic validation blocker at `S0136`.
- The page contract says the English page `S0136.P02` owns “and 50s should
  finally be cashing in, right?”, but the Chinese number anchor “50” was placed
  in `S0136.P01`; the full translation also lacks an explicit “40” anchor.
- 61 editor tasks: 18 high-confidence visual boundary reviews, 18 ordinary
  visual boundary reviews, 8 English-boundary reviews, 7 article-ASR reviews,
  4 page-Chinese continuity reviews, and 3 Chinese semantic reviews.
- Additional page-Chinese examples are fragments such as `S0085.P01`,
  `S0092.P01`, `S0098.P02`, `S0181.P01`, `S0217.P02`, and `S0220.P01`.
- Page translation response itself has one semantic validation error; the
  quality audit has one batch error and zero findings because it did not run to
  completion.

Audit question: this sample is the strongest test of whether page-Chinese
  semantic allocation correctly binds numbers and meaning to page IDs. Do not
  dismiss it as only an API issue.

### F. Dreamcore: historical pre-three-stage sample

Title: `中式梦核：千禧一代的怀旧密码`
Use only the historical artifacts under:
`work-dir/中式梦核：千禧一代的怀旧密码/subtitle/`

This run predates the completed three-stage workflow. It is useful for missed
issue classes such as `4 chan` and `China-eyes`, but it is not a fair measure of
the current parent-ID/page-Chinese contracts. Do not mix its score with White
House, Chocolate, Employment, or Japanese X-generation.

## 6. What The Current Evidence Does And Does Not Prove

Evidence supports these **working hypotheses**, not final conclusions:

- The ownership split is conceptually coherent: English is frozen before LLM
  Chinese allocation, and pages are projected after timing. No artifact here
  proves that the entire three-stage order must be replaced.
- The system has several separate failure classes: ASR/source errors, real
  Chinese semantic/mapping errors, page geometry failures, provider failures,
  and review false positives. Treating all yellow marks as one bug is invalid.
- The repeated `S0026/S0160` failures across two Chocolate runs suggest a shared
  planner/geometry boundary case, not a title-specific translation failure.
- The Japanese `S0136` failure is a page-Chinese identity/anchor allocation
  defect, independent of English parent segmentation.
- The new Chocolate HTTP 500 is an external provider failure; its blocker count
  cannot measure subtitle quality without retrying from retained caches.
- White House demonstrates a passing publication contract but still has a
  non-trivial review queue. A passing manifest is not equal to 95% semantic
  quality, and a large review queue is not equal to a broken pipeline.

## 7. Required Independent Audit Output

The fresh agent should return a compact report with this exact structure:

1. **Bottom line:** is the primary defect in the pipeline order, in one or more
   stage implementations, in review classification, in provider reliability,
   or in artifact/version traceability?
2. **Per-case table:** for White House, old Chocolate, new Chocolate, Employment,
   Japanese X-generation, and Dreamcore: raw artifact, status, genuine defects,
   false/secondary blockers, and confidence.
3. **Cross-case invariant:** one rule supported by at least two cases, with exact
   evidence; do not generalize from one subtitle ID.
4. **Contradictory evidence:** examples that disprove the first hypothesis.
5. **Smallest safe next test:** one offline or cached reproduction that can falsify
   the chosen root cause without changing production code.
6. **Only then:** proposed code change, affected owner layer, regression test,
   risk, and expected improvement.

Do not report a percentage unless the denominator and definition are explicit.
At minimum distinguish: untouched fixed-ID coverage, actionable task coverage,
page-plan pass rate, translation semantic accuracy, and provider success rate.

## 8. Useful Read-Only Commands

```powershell
git status --short
git diff --stat
runtime\python.exe scripts\run_regression.py --profile fast
runtime\python.exe -m pytest tests\test_stable_page_translation_contract.py -q --tb=short
runtime\python.exe -m pytest tests\test_translation_quality_audit.py -q --tb=short
```

For a real case, inspect the manifest and then the matching artifacts in the same
run directory. Never mix a `stable-checkpoints` file with a later
`stable-runs` file unless the report explicitly says it is comparing attempts.

## 9. Current Repository State

- Branch: `main`.
- Verified HEAD: `bb6b4be8a88ab013d0275609c81ef5c539d2a478`.
- Working tree: modified and uncommitted; do not revert or clean it.
- Original project under `D:\软件缓存\VideoCaptioner` is out of scope and must not
  be modified.
- This diagnostic brief is read-only evidence for the next conversation; it is
  not permission to edit production code.
