# Antigravity code audit

Audited on the committed tip `46afccd4f` and repaired on `feature/edify-go-rn-migration`. Antigravity's uncommitted checkout was not edited.

## Defects found and repaired

| Defect | Effect | Fix | Proof |
|---|---|---|---|
| 5 CI jobs red at the tip | Branch could not be trusted | Formatting, lint, CI migrations, fixtures | Local gates pass |
| Planning Oversight answered team lenses with the country summary | Wrong data for a lens | Lens handed on | Integration suite |
| Go stand-in forms replaced real forms | SSA took 2 scores out of 5, wrong forms opened | Only used with Django absent; 8 scores out of 10 | `native_forms_test`, `ssa_scores_test` |
| School writes had no portfolio check | Could reach another officer's school | Scope check | `native_forms_test` |
| Close School opened the Edit form | Wrong action | Kinds separated | `TestOnlyDrawersWithAGoFormAnswerInGo` |
| Page actions were dead in the web app | Buttons did nothing or sent people to the old sign-in | Shared drawer host, planning forms | Browser saves on the private DB |
| Cluster Profile crashed on every tab | Database permission error | Rewritten on the canonical engine | `cluster_profile_test` |
| Cluster Profile had no reader scope check | Any officer could open any cluster by id | Uses `cluster_in_scope` rule | `TestTheClusterProfileIsOnlyForReadersWhoseScopeHoldsIt` |
| Out-of-scope profile answered as a server error | 500 instead of not found | Error mapped | Same test |
| Unassessed schools shown as 0.00 | A missing SSA read as a real result | Not Assessed / Not Compared | `schoolProfileView.test`, `cluster_history_test` |
| Arrived on a field day failed | Server error at every school | SQL parameter types fixed | `TestAFieldDayRecordsArrivingAndLeavingASchool` |
| Five accessibility faults from the UI sweep | Failed the CI sweep job | Roles, focus, link contrast | axe clean on those pages |

## Coverage of the requested feature list

**Exercised in a browser or by integration test:** School Directory, School Profiles, Clusters, Planning (Schedule, Assign, Add to Project), My Plan, Calendar (opens and shows the visit), Smart Route Planner, SSA entry form, Visits (schedule to submitted), GPS display, Notifications (page opens).

**Not individually re-audited in this pass:** Budgeting, Weekly Advance, Financial Approvals, Targets, Impact Assessment, Messaging, Escalations, Decision Log, HR/Leave, Loans, Reports/Exports, Country/Regional Oversight, Python Analytics UI, external integrations. They are covered only by the automated suites.

## Known open items

- `/loans` timed out on desktop in the last hosted UI sweep; not diagnosed.
- Older ledger items not rechecked: audit rows outside the chain, day-pool exporter, TOTP key handling, To-Do parity.
- 91 integration tests skip on this data set.
