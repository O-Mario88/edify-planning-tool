# 4. Migration plan

Dependency-ordered. A step starts only when the steps it depends on have
passed their exit criteria. Reads move before writes in every domain, and
money moves last.

## 4.1 How every step is done

1. **Extract the rule.** Find the rule in the existing code (often inside a
   page view), with its tests and the dated owner decisions beside it. Pin the
   commit it was read from.
2. **Contract.** Add the messages and RPCs; lint and compatibility check.
3. **Read path in Go**, behind the same authorisation the existing
   application applies.
4. **Parity.** A test asks both backends the same question for every seeded
   account and requires identical answers. It runs in CI on every change, so a
   rule changed on `main` shows up as a failure here.
5. **Mobile screen** on the read path.
6. **Write path** only for domains whose reads have held parity: shadow
   comparison on restored data, then an approved single-step cutover of that
   table's writer (see 03, section 3.7).

What must be preserved throughout: existing record ids, Edify School IDs,
Salesforce ids, activity ids, the financial-year arithmetic, role permissions,
approval chains, workflow status values, audit rows and their hash chain,
and all history.

## 4.2 Order

```
M0 foundation (done)
 └─ M1 identity and permissions
     ├─ M2 geography and clusters
     │   └─ M3 school directory and profiles
     │       ├─ M4 planning and scheduling (read)
     │       │   ├─ M5 school visits
     │       │   ├─ M6 trainings and cluster meetings
     │       │   └─ M8 evidence and completion
     │       │       └─ M9 approval and verification workflows
     │       ├─ M7 SSA
     │       └─ M10 partner assignments
     ├─ M11 notifications
     └─ M12 budgets and weekly advances  (after M4–M9)
         └─ M13 reporting and oversight
M14 native mobile features run alongside M5–M8
```

## 4.3 Steps

### M0. Foundation (this assignment)

Gateway, contracts, tracing, errors, health, database guard, read-only role,
authentication against existing tokens, worker, app shell, CI. Slice: an
officer's own schools.

### M1. Staff, roles and permissions

Depends on: M0. Everything else depends on this.

- Port the permission matrix (`ROLE_PERMISSIONS`) as data generated from the
  existing code, not retyped, with a test that fails when the two differ.
- Port scope resolution in layers, each with parity: own schools (done), then
  temporary coverage, supervised team, region reach, country reach bounded by
  country, project and partner portfolios.
- Acting appointments: the swapped permission set and the withheld
  authorities. Until this lands the gateway refuses people in an appointment.
- `AuthService` on the gateway forwarding sign-in, MFA and refresh to the
  existing identity system, so the app uses one base URL.
- Send the caller's permissions to the app as data.

Exit: parity on scope for every role in the seed and on a sanitised restore;
the refusal `ROLE_NOT_MIGRATED` is gone for the roles the app serves.

Risk: highest in the plan. These rules change often on `main`.

### M2. Districts and clusters

Depends on: M1.

- Read: regions, districts, sub-counties, parishes; clusters, membership,
  service districts, scores.
- Rules: cluster in scope (direct versus oversight), schools without a
  district (uploads can have none), cluster score settings.

Exit: parity on cluster lists and membership per account.

### M3. School directory and School Profiles

Depends on: M1, M2.

- Read: directory with the existing filters, profile, closure state and
  history, ownership, data-quality flags, enrolment history.
- Rules: operating versus closed versus soft-deleted, the Core cohort, who may
  see a closed school's profile.
- Write (later, approved separately): edit details, closure and reopening,
  ownership transfer. Each writes audit rows.

Exit: parity on directory and profile for every role; profile screen in the
app.

### M4. Planning and activity scheduling (read first)

Depends on: M3.

- Read: My Plan, Work Plan, calendar, with the planning-year rule and the
  financial-year arithmetic.
- Port `apps/core/fy.py` first, with its boundary tests turned into a shared
  vector file both languages run.
- Rules to extract before any write: one support visit per client, Core
  Trained or Core Graduate school per financial year (staff or partner); the
  Core package split of two staff and two partner; training ceilings counted
  by school; 280 and 560 workload targets that warn and never refuse; holiday
  and leave marks; who may schedule where.

Exit: parity on plan and calendar contents and on every count shown.

### M5. School visits

Depends on: M4.

- Write: schedule, edit while scheduled, reschedule, cancel (cancelling undoes
  every count), group actions.
- Each write appends the same audit and timeline rows as today.

Exit: shadow comparison on a sanitised restore shows identical rows for a
replayed month of visit scheduling.

### M6. Training and cluster meetings

Depends on: M4. Shares the scheduling module with M5.

- In-school training with its visit (the visit carries the cost), group
  training, online training, cluster meetings, attendance.
- Facilitation by a partner is not assignment to that partner.

Exit: as M5, for trainings and meetings.

### M7. SSA assessment and verification

Depends on: M3.

- Read: records, scores, history, year comparison.
- Write: enter scores, one SSA per school per financial year, Programme Lead
  confirms CCEO entries, Impact Assessment keeps partner entries.
- Bulk import stays in the existing application until its own step.

Exit: parity on every SSA figure shown; no second SSA can be created for a
school and year through either backend.

### M8. Evidence and activity completion

Depends on: M5, M6.

- Upload from the phone to the same private store, same metadata row, same
  virus scan, before the record is marked complete.
- Completion with visit or training id, completed date (never in the future),
  partner upload rules.
- The storage keys and metadata of existing evidence are untouched.

Exit: a file completed from the app is indistinguishable, in the database and
the bucket, from one completed on the web.

### M9. Approval workflows

Depends on: M8.

- Programme Lead verifies CCEO and own work; counts follow approval; Impact
  Assessment verifies partner and other staff work; returned reasons; reopen
  requests.
- The audit hash chain: Go reproduces the canonical serialisation byte for
  byte, proven by re-hashing existing rows, before Go appends a single row.

Exit: approval chains replayed on a restore produce the same states, counts
and audit rows.

### M10. Partner assignments

Depends on: M3. Parallel with M4–M9 for reads.

- Hand-overs, allowances, withdrawals, partner team members, partner-dated
  work, invoices per Programme Lead.

Exit: parity on partner lists, counts and remaining allowances.

### M11. Notifications

Depends on: M1.

- Read: the notification centre, preferences.
- Device registration from the React Native app for APNs and FCM, into the
  existing subscription table.
- Sending stays with the existing dispatcher. Go writes to the existing
  outbox in the same transaction as its own change.

Exit: a notification opens its record in the app; delivery records are
unchanged in shape.

### M12. Budgets and weekly advances

Depends on: M4–M9. Deliberately late.

- Read first: activity cost breakdown, cost plan, weekly requests.
- Costing rules: district day mark, night away, shared days, partner rates,
  meals. Ported with the existing recipe-derived health check as the oracle.
- Write: weekly fund requests, advances, disbursement, accountability,
  reimbursement. Paid money locks records.
- Totals are compared to the shilling against the existing application on a
  restore for at least one full financial quarter before any write moves.

Exit: zero differences in every total over the comparison period, signed off
by the Accountant.

### M13. Reporting and oversight

Depends on: M12 for anything with money, M4–M10 otherwise.

- Country Oversight, Planning Oversight, dashboards, exports.
- Heavy aggregation and file exports are where the Python workers earn their
  place: Go authorises and selects, Python computes and renders.

Exit: figures match the existing pages for every role and period.

### M14. Native mobile features

Runs alongside M5–M8.

- Camera and document capture for evidence, location at a visit, offline
  capture with an explicit sync queue, biometric unlock of the stored session,
  push, deep links into records.
- EAS build profiles, crash reporting, store listings, accessibility
  walkthrough with VoiceOver and TalkBack.

Exit: the same flows pass on physical iOS and Android devices.

## 4.4 Keeping up with `main`

`main` moves quickly. Each week: merge `main` into the migration branch, run
the parity and schema contract tests, and treat a new failure as "a ported
rule changed" to be re-read from the existing code. A domain is not ported
while it is being redesigned on `main`; say so and take the next one.

## 4.5 Release gate

Nothing is merged into `main` or deployed until, for the agreed scope:

- [ ] Functional parity is verified.
- [ ] Automated tests pass.
- [ ] Security checks pass, including an authorization review.
- [ ] Performance testing meets agreed targets.
- [ ] Data integrity and migration rehearsals pass on a sanitised restore:
      record counts, identifiers, relationships and financial totals.
- [ ] iOS and Android builds are verified on devices.
- [ ] Authorised users complete acceptance testing.
- [ ] Rollback or forward recovery is documented and tested, including a
      backup restoration.
- [ ] Staging and development are shown to be unable to reach production.
- [ ] Explicit approval to merge and deploy is given.

Cutover is its own decision after that: which traffic, which tables, in what
order, with the existing application left available until the new path is
validated.

## 4.6 Performance targets (proposed, to be agreed)

| Measure | Proposed target |
|---|---|
| Gateway read, p95, at production size (about 17,000 schools) | 150 ms |
| Scheduling one visit, p95 | 400 ms, against 2.4 s measured today for a reschedule |
| Cluster bulk schedule of 50 schools | 2 s, against 5.6–18.9 s today |
| App cold start to first screen on a mid-range Android phone | 2.5 s |
| App list scroll | no dropped frames at 60 Hz with 1,000 rows |

## 4.7 Next milestone

M1, starting with the three pieces that unblock everything else:

1. The permission matrix generated from the existing code, with its
   difference test.
2. Scope parity for supervised teams and country roles, so Programme Leads and
   country roles are served.
3. `AuthService` forwarding on the gateway, and the first native build of the
   app through EAS on one iPhone and one Android phone.
