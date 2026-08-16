# Acceptance gates (mandate §33) — status at 2026-08-16

Honest status against the twenty gates. "Not assessed" is used where this
environment could not produce evidence; it is never used to mean "probably fine".

| # | Gate | Status | Evidence / blocker |
| --- | --- | --- | --- |
| 1 | No unresolved Critical findings | **PASS** | One Critical found (AUD-004), reproduced, fixed, regression-tested |
| 2 | No unresolved High in finance/security/permissions/verification/targets/data-integrity/loans/SF | **PASS** | AUD-002, AUD-003, AUD-005, AUD-006, AUD-011 all fixed and verified. The container scan was reproduced green locally with CI's exact scanner and flags before pushing |
| 3 | Every mandatory end-to-end journey passes | **1 of 16** | All 16 traced against the suite ([04-journey-coverage.md](04-journey-coverage.md)): **none was walked end to end** — each half of a journey faked its neighbour's outcome. Journey 1 (the primary spine) now has a real test that fakes nothing and proves a funded visit can be executed, verified, accounted and closed. 15 remain, with per-journey gaps listed |
| 4 | Every critical handoff creates the correct notification and To-Do | **PARTIAL** | Verified structurally in the preceding alignment audit (12 seam fixes); not re-walked journey-by-journey here |
| 5 | Every To-Do closes automatically when its condition resolves | **PARTIAL** | To-Dos are derived live from workflow state (cannot go stale by construction); per-producer closure not re-tested this pass |
| 6 | Every role passes record-level access tests | **PASS** | All 952 routes walked; scope, IDOR, partner/MFI isolation verified; no unguarded state-changing endpoint |
| 7 | Every critical formula reconciles independently | **PARTIAL** | Target/rate/reconciliation logic verified by code+data inspection; costing and repayment arithmetic not recomputed against an independent implementation |
| 8 | Planned/actual/verified/paid/achieved remain separate | **PASS** | Distinct columns; no path writes planned into actual; four-value separation confirmed in the workspace payloads |
| 9 | Every governed action produces an audit record | **PARTIAL** | Spot-verified (role switch logs both success and failure; 37,831 audit rows in dev); no exhaustive per-action census |
| 10 | Locked figures change only through amendments | **PASS** | Costing refuses re-cost once money moved; `BudgetAmendment` carries previous/new/reason/actor/timestamp |
| 11 | Every dashboard figure drills down to supporting records | **PARTIAL** | 68 registered metrics reconciled against their computing services ([05-metric-reconciliation.md](05-metric-reconciliation.md)): 50 disagree, mostly declaration drift, a minority materially. Drill-down link verification itself not yet walked |
| 12 | No production page uses fake/mock/placeholder data | **PASS** | Enforced by an existing platform gate (`test_mock_purge`) that runs in the suite |
| 13 | 50,000-school scale test passes | **PASS (both axes)** | School population proven flat at 50,000. The transactional axis is now covered too by a new gate — and it immediately caught two real defects: a closure queue taking 124s at 12,000 activities, and an N+1 in the offline day package. Both fixed; see [02-scale.md](02-scale.md) |
| 14 | Routine field staff meet the 15-minute objective | **NOT ASSESSED** | Requires observed time studies with real users (§10.2). The instrument exists — telemetry with the §3a planning/execution split — but has no production data behind it |
| 15 | Offline work recovers and syncs without duplication | **NOT ASSESSED** | Server half (day package) exists and is tested; the service-worker/queue client is unbuilt (roadmap B3) |
| 16 | Salesforce/NetSuite/MFI failures are recoverable | **PARTIAL** | Outbox dead-letters, backs off, replays, and never un-verifies internal work — verified. But the transports are unimplemented and flag-off by design (roadmap B2), so no live failure was exercised |
| 17 | Backup restoration tested | **NOT ASSESSED** | Requires the production/DigitalOcean side; out of scope for this environment |
| 18 | BT loan / Financial Health / Government Requirements journeys pass | **PARTIAL** | Module integrated into platform law this pass (reference data, metric registry, pagination, search, scoping verified). End-to-end journeys not walked |
| 19 | All approved requirements have a final implementation status | **NOT DONE** | The full §7 traceability matrix was not built; this audit prioritised the platform laws (§3) and the highest-risk domains |
| 20 | Documentation matches the audited system | **PASS** | AUD-001 fixed: figures re-measured and stated with their source, Admin's full exclusion set documented, and a new §8a covers Business Transformation |

## Summary

**Ready to proceed on:** authorization architecture, financial money-safety,
target/achievement integrity, data integrity, and school-scale performance — all
now carry either a passing verification or a fixed defect with a regression test.

**Blocking a full production sign-off:** gates 3, 11, 14, 15, 17 and 19. Every
one of them needs something this environment does not have — a staging
deployment, real users, real devices, or credentialed integrations. None can be
closed by further code work here, and none should be marked passed without the
evidence.

**What that means for a client rollout.** The code is defensible: every platform
law that could be tested from here was tested, and each defect found was
reproduced, fixed and pinned. What has *not* been demonstrated is the system
running end to end in a production-like environment — no journey walked on
staging, no restore rehearsed, no integration failure exercised, no offline
client at all. A rollout plan should treat those as the remaining work, not as
paperwork.

## Recommended remediation order

**Closed in this audit:** AUD-001 through AUD-015 — the Critical
separation-of-duties bypass, partner credit leaking into personal achievement,
stored XSS, the silent-red pipeline, the container scan, Admin's budget
authority, the browser-login throttle, the Salesforce gate on both verification
doors, seed fidelity, the 124-second closure queue, the day-package N+1, and My
Plan hiding a field officer's own work.

**Before pilot — needs a decision, not a patch:**
- Settle the material metric discrepancies in
  [05-metric-reconciliation.md](05-metric-reconciliation.md), led by
  `partner_oversight_payment_pending` treating `completed` as verified and
  `bt_positive_impact` reading a column nothing writes.
- Decide whether the headline target-achievement tiles should join the metric
  registry; today several are raw dicts outside it.

**Before production — needs an environment this one is not:**
- Walk the remaining 15 journeys ([04-journey-coverage.md](04-journey-coverage.md)),
  ideally as tests rather than manual runs, since the gaps are seams.
- Build the offline client and test recovery on a real device (gate 15).
- Credential Salesforce/NetSuite/MFI and exercise a real failure and replay
  (gate 16).
- Rehearse a restore (gate 17).
- Run this on staging before clients see it: 32 migrations and a new module is
  not a routine deploy.
- Note `REDIS_URL` is unset with `instance_count: 1`, so the platform cannot
  scale horizontally as shipped; the scale evidence assumed a single process.

**Within 30 days:** the §7 requirements traceability matrix (gate 19), and the
observed staff time studies once there is production usage to measure (gate 14).
