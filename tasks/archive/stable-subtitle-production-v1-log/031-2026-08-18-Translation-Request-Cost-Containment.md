## 2026-08-18 Translation Request Cost Containment

- Preserved the existing Pro full-translation and Flash allocation role split.
  The change does not alter frozen English, IDs, word ownership/times, Chinese
  acceptance rules, display pages, or synthesis inputs.
- Replaced per-group Pro recovery with bounded 8/4/2/1 missing-group batches.
  A run makes at most 12 full-translation repair requests; unresolved groups
  fail explicitly after the budget rather than expanding into dozens of calls.
- A partial response now checkpoints only groups with valid expected IDs,
  source echoes, and non-empty Chinese. Those successes survive restart, while
  duplicate, unknown, empty, and source-mismatched records remain unusable.
- Disabled OpenAI SDK automatic retries for the screen editor so application
  attempts are the single retry authority.
- Added an atomic `llm-request-ledger.json` checkpoint and manifest summaries
  for task/model request count, latency, cache hits, prompt/completion/cache-hit
  tokens, and reasoning tokens when the provider returns them. Prompts and API
  keys are not recorded.
- Focused tests, the complete stable-caption smoke suite, and
  `runtime\python.exe scripts\run_regression.py` pass without any network or
  paid model request.

