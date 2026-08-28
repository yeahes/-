## 2026-08-16 Display-Page Chinese Stale-State Correction

- Root cause: the manual editor compared concatenated page-local Chinese with
  the parent cue. Valid page translation may reorder wording across pages, so
  this incorrectly marked 29 translated pages as stale and yellow.
- New-schema artifacts now use their explicit `source_parent_chinese` binding
  for parent drift detection. Legacy artifacts keep the aggregate fallback.
- The fresh oil run reopens as 163 display pages with zero missing Chinese and
  zero stale-Chinese rows; four English-boundary review rows remain unchanged.
- Manual editor tests and the complete regression command pass. The replay was
  read-only and did not modify production output.

