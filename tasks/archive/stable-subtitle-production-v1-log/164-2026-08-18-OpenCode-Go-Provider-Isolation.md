## 2026-08-18 OpenCode Go Provider Isolation

- Added an independent OpenCode Go provider using the official OpenAI-compatible
  `https://opencode.ai/zen/go/v1` base. Ordinary allocation and display-page
  translation default to `deepseek-v4-flash`; complete semantic translation
  and bounded quality retries default to `deepseek-v4-pro`.
- Replaced duplicated provider branches with one resolver used by subtitle task
  creation, article analysis, vocabulary/manual-polish requests, and the
  allocation-only replay utility. DeepSeek official and OpenCode Go keep
  separate persisted keys and model fields.
- Removed LM Studio, Gemini, ChatGLM, and the public model from the visible
  settings choices while retaining legacy identifiers for safe deserialization.
- Added offline regression coverage for visible choices, credential isolation,
  role-model freezing, and vocabulary routing. The complete regression command
  and diff check pass; no paid request or production artifact write was used.

