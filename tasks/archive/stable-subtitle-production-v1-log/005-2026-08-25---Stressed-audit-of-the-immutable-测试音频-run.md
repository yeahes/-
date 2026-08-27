## 2026-08-25 - Stressed audit of the immutable 测试音频 run

- Read every selected parent and actual page in the immutable
  `20260824T201840.701773-2290bd40` run: 43 stressed parents and 79 pages.
  Identity, parent Chinese, page coverage, and page non-emptiness all passed.
- This run is explicitly a baseline because it carries prompt versions v7/v4;
  it cannot prove or disprove the current v8/v5/v10 translation changes.
- The main confirmed page-Chinese problems were S0004, S0010, S0021, S0023,
  S0045, S0083, S0096, and S0115. S0115 additionally exposes an English page
  boundary issue. No synthesis blocker or missing page was present.
- Next evidence needed is one fresh unreviewed automatic run using the current
  prompt identities. Do not re-run the manually corrected episodes.

