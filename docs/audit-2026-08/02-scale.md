# Scale verification — the 50,000-school gate (mandate §25, acceptance §33.13)

**Verdict: PARTIAL PASS.** The school-population dimension is proven at 50,000.
The transactional-volume dimension is not covered and remains an open obligation.

## What was run

```
EDIFY_SCALE_SCHOOLS=50000 EDIFY_SCALE_GROWTH=10000 \
  python manage.py test apps.system_health.test_load_scale
```

Result: **15 tests, OK, 120s.**

The gate is well designed for this question: it asserts **scale-invariance**
(measure a page, grow the estate by 10,000 schools, measure again — the query
count must not move) rather than a fixed query ceiling. An invariant page is
correct at any estate size, which is a stronger claim than "it worked at 50,000".

## Measured p95 latency at 50,000 schools

| Surface | p95 | Objective | Result |
| --- | --- | --- | --- |
| /dashboard | 265 ms | 800 ms | pass |
| /my-plan | 77 ms | 800 ms | pass |
| /schools | 221 ms | 800 ms | pass |
| /todos | 167 ms | 800 ms | pass |
| /notifications | 19 ms | 800 ms | pass |
| /settings | 15 ms | 800 ms | pass |
| /analytics | 749 ms | 1500 ms | pass |
| /system-health | 7 ms | 1500 ms | pass |

Scale-invariance additionally verified for: /planning, school profile,
/core-schools, /projects, the finance queue, the closure queue, and the CD
dashboard over both school growth and roster growth.

Laptop wall time under `manage.py test` is not production wall time; these
figures are comparative evidence of flat cost, not an SLO measurement.

## What this does NOT prove

The fixture builds geography, 50,000 schools, staff-school assignments, and SSA
records. It does **not** build proportional volumes of the transactional estate
that mandate §6.4 requires:

- activities, evidence records, attendance
- budget lines, fund requests, approvals, disbursements, accountability
- audit events, notifications, To-Do-producing states, messages
- target allocations and achievement credits
- **BT loans, repayment snapshots, compliance records** — the Business
  Transformation surfaces are outside the scale gate entirely

So a page that is O(1) in *schools* could still be O(n) in *activities* or
*loans* and pass this gate.

## Open obligations before §33.13 can be signed off

1. Extend the fixture with a realistic transactional mix at 50,000-school ratios
   (document the ratio assumptions where production data cannot supply them).
2. Add the BT loan register, MFI portal, repayment reporting, and the closure and
   accountability queues to the invariance list.
3. Run the concurrency/load scenarios of §25.1 (login peak, fund-request
   deadline, month-end consolidation) against a staging deployment — not a
   single-process test runner.

## Related work done during this audit

The BT tables were unbounded when the module landed; nine of them were wired to
the shared server-side pager during the preceding integration pass, so the loan
register no longer renders an unbounded result set. That removes the most obvious
scale hazard on the newest surface, but is not a substitute for measuring it.
