# Scale verification — the 50,000-school gate (mandate §25, acceptance §33.13)

**Verdict: PASS on both axes.** The school-population dimension is proven at
50,000, and the transactional dimension — the half this document originally
recorded as unproven — is now covered by a second gate.

Building that second gate was worth it on the first run: it immediately caught
two real defects that the school-population gate could never have seen, because
both are flat in schools and steep in work done. See "The transactional axis"
below.

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

## The transactional axis (added 2026-08-16)

`TransactionalVolumeScaleTest` in the same file asks the other question: a page
can be O(1) in schools and O(n) in the work done at them, and activities,
evidence, fund requests and loans accumulate far faster than schools do.

Same assertion shape, different axis — measure, add tens of thousands of
activities across the lifecycle statuses, measure again, and require the query
count not to move. Configurable via `EDIFY_SCALE_ACTIVITIES` and
`EDIFY_SCALE_ACTIVITY_GROWTH`.

It found two defects on its first run:

| Surface | Symptom | Cause |
| --- | --- | --- |
| `/activities/closure/` | **124.5 seconds** at 12,000 activities | Evaluated every activity ever executed on page load, each in its own transaction — and twice per row, because `is_eligible()` re-ran `evaluate()` |
| `/today` | queries grew 176 → 240 with volume | `missing_evidence_kinds()` read `activity.evidence` per row — an N+1 in the offline field payload |

Both fixed (AUD-012, AUD-013). The gate's whole run fell from 180s to 66s, and
`/my-plan`, `/dashboard`, `/todos`, `/today` and the closure queue are now flat
in transactional volume.

## What is still not proven

- Evidence files, notifications, messages and BT loans are not yet in the
  transactional fixture — only activities, at realistic lifecycle spread.
- The concurrency and peak-load scenarios of §25.1 (login peak, fund-request
  deadline, month-end consolidation) need a staging deployment; a single-process
  test runner cannot answer them.
- `REDIS_URL` is unset and every service runs at `instance_count: 1`, so all of
  this evidence describes a single process. Horizontal scaling is a config
  change that has not been exercised.

## Related work done during this audit

The BT tables were unbounded when the module landed; nine of them were wired to
the shared server-side pager during the preceding integration pass, so the loan
register no longer renders an unbounded result set. That removes the most obvious
scale hazard on the newest surface, but is not a substitute for measuring it.
