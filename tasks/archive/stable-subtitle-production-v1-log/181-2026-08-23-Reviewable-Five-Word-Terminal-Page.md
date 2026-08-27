## 2026-08-23 Reviewable Five-Word Terminal Page

- Reproduced Chocolate `v29 S0160` from the immutable word ledger and exact
  word times. Its old passing `v27` projection used 11+5 words at 56px, while
  the current six-word secondary-review preference discarded the complete
  five-word terminal phrase and blocked the parent.
- Separated the style preference from renderability only for a sentence-
  complete five-word prepositional terminal page. Word coverage/order, lexical
  boundaries, 56px layout, and 900ms minimum timing remain hard; the boundary
  stays REVIEW-labelled.
- A first four-word implementation changed passing White House `S0017` from
  5+10 to 11+4 and was rejected. The final five-word floor restores the frozen
  White House plan exactly while fixing the Chocolate real-timing case.
- Focused positive and negative tests pass. Read-only White House replay builds
  all 217 plans with zero page-range or font-signature changes. The complete
  article readability contract passes 104/104 in 411.23 seconds.

