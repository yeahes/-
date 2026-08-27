## 2026-08-21 Empty Chinese Projection And Generic Retry

- Root cause: a frozen fragment page was required to read as an independent
  Chinese sentence while page text was forbidden from exceeding authoritative
  parent Chinese. The model repeatedly invented a nominalizer to satisfy both.
- The prompt now permits natural cross-page Chinese continuation when the fixed
  English page is itself a fragment or review boundary. Validator evidence is
  converted into exact retry constraints for any added token, repeated phrase,
  or missing page ID; no sample-specific allowlist entry was introduced.
- A live isolated S0133 request failed the first strict semantic check and
  passed its second request. Existing S0227/S0229 page plans also pass, with
  `1.4 billion` remaining indivisible.
- Editor projection of the old chocolate checkpoint exposes all four missing
  page translations as red `待分配` placeholders. Stored/edit values remain
  empty and the only background colors are yellow and red.
- Page translation, article readability, review-mark, and manual-final suites
  pass. Full regression is delegated to the user after final diff review.

