# Acceptance gates (mandate §33) — status at 2026-08-16

Honest status against the twenty gates. "Not assessed" is used where this
environment could not produce evidence; it is never used to mean "probably fine".

| # | Gate | Status | Evidence / blocker |
| --- | --- | --- | --- |
| 1 | No unresolved Critical findings | **PASS** | One Critical found (AUD-004), reproduced, fixed, regression-tested |
| 2 | No unresolved High in finance/security/permissions/verification/targets/data-integrity/loans/SF | **PASS** | AUD-002, AUD-003, AUD-005, AUD-006, AUD-011 all fixed and verified. The container scan was reproduced green locally with CI's exact scanner and flags before pushing |
| 3 | Every mandatory end-to-end journey passes | **NOT ASSESSED** | §29's 16 journeys need a staging environment with real integration credentials and human actors; not performable here |
| 4 | Every critical handoff creates the correct notification and To-Do | **PARTIAL** | Verified structurally in the preceding alignment audit (12 seam fixes); not re-walked journey-by-journey here |
| 5 | Every To-Do closes automatically when its condition resolves | **PARTIAL** | To-Dos are derived live from workflow state (cannot go stale by construction); per-producer closure not re-tested this pass |
| 6 | Every role passes record-level access tests | **PASS** | All 952 routes walked; scope, IDOR, partner/MFI isolation verified; no unguarded state-changing endpoint |
| 7 | Every critical formula reconciles independently | **PARTIAL** | Target/rate/reconciliation logic verified by code+data inspection; costing and repayment arithmetic not recomputed against an independent implementation |
| 8 | Planned/actual/verified/paid/achieved remain separate | **PASS** | Distinct columns; no path writes planned into actual; four-value separation confirmed in the workspace payloads |
| 9 | Every governed action produces an audit record | **PARTIAL** | Spot-verified (role switch logs both success and failure; 37,831 audit rows in dev); no exhaustive per-action census |
| 10 | Locked figures change only through amendments | **PASS** | Costing refuses re-cost once money moved; `BudgetAmendment` carries previous/new/reason/actor/timestamp |
| 11 | Every dashboard figure drills down to supporting records | **NOT ASSESSED** | Requires the per-metric reconciliation of §21.2 across all dashboards |
| 12 | No production page uses fake/mock/placeholder data | **PASS** | Enforced by an existing platform gate (`test_mock_purge`) that runs in the suite |
| 13 | 50,000-school scale test passes | **PARTIAL** | See [02-scale.md](02-scale.md): school-population dimension proven; transactional volume not covered |
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

**Done this pass:** AUD-001, AUD-002, AUD-003, AUD-004, AUD-005, AUD-006,
AUD-007, AUD-010, AUD-011, and the SF-ID half of AUD-009.

**Before pilot (open, each needs a decision rather than a patch):**
- Enforce the Salesforce ID at IA verification, or accept that an activity can
  be verified without one and then never closed (AUD-009, related risk).
- Decide the mixed-counting-basis behaviour in `refresh_period_targets`
  (AUD-009 item 2) — latent today, wrong the moment a milestone mixes bases.
- Make the formatter check a separate always-first CI job with an alert, so the
  silent-red mode of AUD-002 cannot recur.
- Reseed or accept the 23,560 impossible SSA rows in dev (AUD-008).

**Before production:**
- Extend the scale fixture to transactional volume and add BT surfaces (gate 13).
- Build the offline client and test real-device recovery (gate 15).
- Credential the integrations and exercise real failure/replay (gate 16).
- Run the §29 journeys on staging (gate 3) and the §21.2 metric reconciliation
  (gate 11).
- Rehearse a restore (gate 17).

**Within 30 days:** build the §7 requirements traceability matrix (gate 19), and
run the observed time studies once there is production usage to measure (gate 14).
