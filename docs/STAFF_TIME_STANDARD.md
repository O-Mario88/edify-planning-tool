# The Staff Time Standard — 15 minutes of administration per field day

*Adopted 2026-08-14. This standard sits beside
[PRODUCT_PRINCIPLES.md](PRODUCT_PRINCIPLES.md) and carries the same weight:
a feature that violates it should not ship without a documented exception.*

---

## 1. The requirement

> **At least 95% of routine field-staff workdays must require no more than
> 15 minutes of active administrative interaction with the platform.**

The platform exists to convert strategy, school needs, staff capacity,
geography, approved budgets and verified results into the next best field
actions — not to consume the field day it is meant to organise. Staff time
spent operating the platform is overhead on the mission, and overhead is
governed the way this platform governs everything else: measured, ratcheted
and audited — never assumed.

## 2. Who it covers

The 15-minute ceiling applies to roles whose primary responsibility is
field implementation:

- CCEOs
- Partner Field Officers
- Project Coordinators
- Program Leads, for routine supervision days

Impact Assessment and Accountants do verification and financial processing
*inside* the platform as their actual job; for them the standard instead
requires a daily decision briefing consumable in 15 minutes, with
productivity governed by batch-processing time and exception throughput —
not by total time in the platform.

## 3. What counts as active interaction

**Counted**: navigating between pages, entering information, approving or
submitting items, uploading evidence (the attended portion), correcting
errors, searching for schools or activities.

**Not counted**: background synchronisation, uploads that continue after
submission, route guidance running while travelling, automated processing,
and reading a briefing the platform prepared.

## 3a. The six sanctioned routine interactions

The ceiling is not only about *how much* time — it is about *what the time
is for*. Planning is the platform's work; execution is the staff's. A
routine field day's interactions should reduce to six kinds:

1. **Schedule** — accept or adjust the prepared plan and dates.
2. **Assign** — hand work to a partner or staff member where needed.
3. **Debrief** — confirm the prepared end-of-day summary.
4. **Evidence** — capture and upload what the activity requires.
5. **Salesforce ID** — paste the SF reference proving the data entry was
   made in Salesforce.
6. **NetSuite ID** — paste the NetSuite reference proving the financial
   accountability was completed in NetSuite.

Everything else a routine day currently requires — constructing plans
school by school, computing costs, assembling fund requests, writing
debriefs from scratch, re-entering planned figures — is preparation, and
preparation belongs to the platform. Time on planning surfaces is
therefore measured separately (§4) and its target is to trend toward
zero as the preparation layer lands; the five/six interactions above are
what remains. (The SF/NetSuite paste steps themselves exist to be
eliminated by direct integrations — see the roadmap's Phase 2 — at which
point proof arrives by sync, not typing.)

## 4. How it is measured

Directly, from product telemetry — never by asking staff to estimate.

- The platform records one interaction event per authenticated request
  (the **resolved route pattern** and timing only — never query strings,
  never form contents).
- A daily rollup sessionises each person-day: consecutive events closer
  than the idle cap (3 minutes) form an active session, contributing their
  real gaps; each session additionally earns a 30-second final-action
  credit (server timestamps cannot see the last interaction's own
  duration, and a lone check-in should count as ~30 seconds, not zero).
  A person-day's active time is the sum of its sessions.
- The standard's metric is computed over **role populations**:
  the share of field-role person-days at or under 15 minutes, and the
  p50/p90/p95 active minutes per role.
- Active time is additionally attributed to **interaction categories** by
  the route worked on — *planning* surfaces (plan construction, costing,
  fund preparation, target distribution), *execution-and-proof* surfaces
  (the §3a interactions), and *other* (dashboards, messages, settings).
  The planning share of field-role active time is reported beside the
  ceiling, and its target direction is down: as the preparation layer
  lands, a field day's remaining minutes should be execution and proof.

This is an estimate by construction (server-side sessionisation cannot see
thinking time versus typing time). It is used as a *trend and ceiling*
instrument, and its method is versioned with this document so the number is
never silently redefined.

## 5. The anti-surveillance constraints (non-negotiable)

The Healthy principle already forbids surveillance. Applied to this
standard:

1. **Aggregate only.** The SLO is reported as population percentiles and
   shares, by role and period. No surface — dashboard, export, API or
   report — may present a named individual's active minutes to a manager.
2. **No ranking.** Interaction time must never appear in any leaderboard,
   performance review, target, or comparison between named staff.
3. **Computation is not exposure.** Per-person-day rows exist only to
   compute percentiles; they are retained briefly (see §6), carry no
   content, and have no user-facing representation.
4. **The metric judges the platform, not the person.** A rising number is
   a product defect to fix, never a staff behaviour to correct.

A feature that needs to break one of these constraints is out of scope for
this platform.

## 6. Data handling

- Events store: actor id, role, timestamp, HTTP method, resolved route
  pattern, response duration. Nothing else — no URLs with identifiers, no
  query strings, no payloads, no IP addresses.
- Raw events are pruned after 14 days; only the per-day aggregates
  (person-day active minutes, counts) and the role-level report series are
  retained.

## 7. Governance

- The report lives in the platform's system-health surface (admin), beside
  the other self-audits.
- Changes to the ceiling, the covered roles, the idle cap, or the
  measurement method are amendments to this document, made in a reviewed
  commit — not configuration edits.
- Every roadmap feature aimed at staff time states its expected effect on
  this metric, and the metric's movement after release is the honest test
  of whether it worked.

## 8. Why 15 minutes

A typical five-visit field day, fully supported, decomposes to roughly:
2 minutes accepting the prepared day, 10–15 seconds of check-in per school,
1–1.5 minutes of actuals-and-evidence per activity, 3 minutes reviewing the
prepared debrief and accountability, and a 2-minute buffer for one
exception — about 12–15 minutes. The ceiling is deliberately set at what a
*fully automated* preparation layer makes possible, so the gap between
today's measurement and 15 minutes is the roadmap's honest backlog.
