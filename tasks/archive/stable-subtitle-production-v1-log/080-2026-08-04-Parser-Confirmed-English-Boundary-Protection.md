## 2026-08-04 Parser-Confirmed English Boundary Protection

- Root cause: stable pre-ID cutting did not protect several parser-confirmed
  local dependencies, allowing a cue boundary after an object before a content
  clause, inside compact coordination, or before a verb-attached post-object
  modifier.
- Added local, pause-aware protections for these dependency shapes. A
  comma-delimited `but`, `or`, `so`, or `yet` finite-clause transition remains
  outside the compact-coordination rule so approved visual temporal splits are
  preserved.
- Regressions cover coordinated predicates and lists, object-content clauses,
  object-attached modifiers, and the existing non-finite-prefix/visual-clause
  behavior. English text, word order, word timestamps, post-ID timing,
  Chinese allocation, and export are unchanged.

