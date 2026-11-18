# Edify technology migration

Go gateway and core modules, Python analytics workers, React Native mobile app,
Protocol Buffer contracts. This replaces the earlier Capacitor direction for
mobile; the Capacitor shell in `mobile/` is left as it is and is not the
target.

Branch: `feature/edify-go-rn-migration`, cut from `main` at `deefe6f6f`
(2026-11-09, CI green, deployed). Nothing on this branch is merged into `main`,
deployed, or connected to production.

| Document | What it holds |
|---|---|
| [01-audit.md](01-audit.md) | What the existing application is, measured from the code |
| [02-target-architecture.md](02-target-architecture.md) | The design: gateway, modules, contracts, workers, mobile app |
| [03-database-protection.md](03-database-protection.md) | How production data is kept out of reach, and how that is enforced |
| [04-migration-plan.md](04-migration-plan.md) | Dependency-ordered plan for every domain, and the release gate |
| [05-environments-and-staging.md](05-environments-and-staging.md) | Development setup, staging deployment, CI and branch protection |
| [07-school-loan-portal.md](07-school-loan-portal.md) | The School Loan Application Portal: journeys, roles, running it, open questions |
| [08-sign-in.md](08-sign-in.md) | Sign-in, owned by Go: the existing rules ported, what it writes, what has not moved yet |
| [09-accounts-and-roles.md](09-accounts-and-roles.md) | Accounts and roles, owned by Go: role switching, the forced password change, the Admin's Users screen |
| [10-teams.md](10-teams.md) | Staff and partner teams, owned by Go: supervisors, managed teams, a partner's own team, logins and schools |
| [11-acting-leadership.md](11-acting-leadership.md) | Acting leadership, owned by Go: appointing, moving and cancelling acting leaders, and the appointee's switch into the acting capacity |
| [12-school-directory.md](12-school-directory.md) | The School Directory, read by Go: whose schools, filters, tabs and rows, proved against the existing page; writes and profiles not yet moved |
| [13-school-profiles.md](13-school-profiles.md) | School Profiles: who may open a school, the header and its doors, the visit rule, and every tab (Overview, SSA, Participation, Projects, Stories, Academic, Core School, Details) of an open school, Core schools included, read by Go; the plan for the rest |
| [14-districts-and-clusters.md](14-districts-and-clusters.md) | Districts and clusters (M2): the Clusters page read by Go (whose clusters, filters, strip, cards, doors, pages), proved against the existing page; a card's schools, the cluster and district profiles and every save not yet moved |
| [15-cluster-oversight.md](15-cluster-oversight.md) | Cluster Oversight's Command Center (the one address of the page the app opens), read by Go; its sections are not opened by the app |
| [16-closed-schools.md](16-closed-schools.md) | The Closed Schools archive, read by Go |
| [17-programme-schools.md](17-programme-schools.md) | Programme Schools (Core Trained, Core Graduate, Champion), read by Go |
| [18-decision-log.md](18-decision-log.md) | The Decision Log, read by Go through a narrow view of the audit chain (decision rows, subject keys only) |
| [19-escalations.md](19-escalations.md) | Escalations, read by Go; raising and deciding stay with the existing application |
| [20-field-debriefs.md](20-field-debriefs.md) | Field Debriefs: not moved; the map and what it waits on (HR reach, covering-lead rosters, partner scope) |
| [21-my-actions.md](21-my-actions.md) | My Actions and Actions Sent, read by Go |
| [22-core-schools-oversight.md](22-core-schools-oversight.md) | Core Schools Oversight, read by Go; its Core School Visits and Trainings tabs wait on My Plan |
| [24-planning-page.md](24-planning-page.md) | Planning (M4): every tab of `/planning` read by Go (filters, strip, workload line, rows, cluster cards, doors, pages); a priority allocation's page and every save not yet moved |
| [25-my-plan.md](25-my-plan.md) | My Plan (M4): piece 1, the page for staff who hold nothing yet, read by Go; the map of the rest and its split into pieces 2–6 |
| [26-shadow-writes.md](26-shadow-writes.md) | The harness every save is proved with before Go writes it: two copies, the existing app's drawers played on one, a table-by-table comparison; proved against itself |
| [27-first-save-schedule-visit.md](27-first-save-schedule-visit.md) | The first save in Go, scheduling a school visit: what one save writes (measured), the split (Go saves, money stays until M12), the first piece's scope, contract, writer role and proof; one owner decision |
| [28-web-foundation.md](28-web-foundation.md) | The Next.js web foundation (M15): sign-in through the gateway, httpOnly session cookies, the shell, the existing web's tokens copied and checked, generated Connect clients, the School Directory from Go's answer, compared with Django at 1440 and 390 pixels |
| [29-second-save-reschedule-visit.md](29-second-save-reschedule-visit.md) | The second save in Go, rescheduling a school visit; the owner's decision on `activity.status` and the day's batch |
| [30-third-save-cancel-visit.md](30-third-save-cancel-visit.md) | The third save in Go, cancelling a school visit; the narrow function that withdraws its unmoved advance |
| [31-fourth-save-edit-visit.md](31-fourth-save-edit-visit.md) | The fourth save in Go, editing a scheduled school visit's goal and expected outcome; the app's Edit drawer reason field |
| [32-fifth-save-training-pair.md](32-fifth-save-training-pair.md) | The fifth save in Go, an In-school Training and its school visit as one save; the audit-seal defect found by its proof and fixed in Django |
| [33-sixth-save-group-actions.md](33-sixth-save-group-actions.md) | The sixth save in Go, group reschedule and group cancel from the bar for ticked rows; a group Go cannot take whole is forwarded whole; the group check door (33.9) lets Go take groups onto a new day and groups its pricing refuses |
| [80-multi-country-phase-0.md](80-multi-country-phase-0.md) | Edify Global, Phase 0: the multi-country audit (what carries a country today, the Uganda assumptions, the school-country leak), the proposed country model, the isolation assessment, the plan, the owner's decisions, Phase 1's country registry (§8), its row-level security and settings API (§9), country memberships (§10), the Admin pages (§11) Phase 3's role and scope per country (§12) the country through planning (§13) and through SSA (§14) |

The code is under [`platform/`](../../platform/README.md).

## Where things stand

Updated 2026-11-13. Nothing on this branch is merged into `main`, deployed, or
connected to production; every Go save below is behind `EDIFY_GO_SAVES`, off
by default and refused in test and production.

Done on this branch:

- Foundation (M0): audit and baseline; contracts with lint, compatibility check
  and reproducible generation; the Go gateway (health, structured errors,
  tracing, the production-database guard, the read-only role); the Python
  analytics worker; CI (`platform-ci.yml`).
- Identity (M1): sign-in, accounts and roles, teams, acting leadership owned by
  Go (08–11).
- Pages read by Go, each proved for every seed account against the existing
  feed: School Directory and School Profiles (12, 13); Clusters, Cluster
  Oversight, Closed Schools, Programme Schools (14–17); Decision Log,
  Escalations, My Actions and Actions Sent, Core Schools Oversight (18, 19, 21,
  22); Planning (24); My Plan, in pieces (25).
- Saves made by Go, each proved in shadow at the service and the app level
  (0 steps and 0 changed tables differing, the audit chain verifying):
  schedule, reschedule, cancel and edit a staff school visit (27, 29–31); an
  In-school Training with its visit (32); group reschedule and group cancel
  (33).
- The audit seal fixed in Django on this branch: every decorated save is sealed
  at its own commit (32.8). `main` keeps the defect until the owner approves it.
- React Native app (`platform/mobile`) drawing every page from the gateway;
  Next.js web foundation with the School Directory (28).

Not done, and not claimed:

- Pages still served only by the existing application: most of the 264 full
  pages (`docs/platform-page-inventory.json`), among them the Calendar, Work
  Plan, To-Do, Team Performance, Field Debriefs (20), SSA, completion and
  evidence, approvals, partners, notifications, budgets and reporting.
- Saves still made only by the existing application: every save beyond the
  seven above (group, online and cluster trainings and meetings, SSA,
  completion, verification, partner work, money).
- No replayed month on a sanitised restore (M5's exit) — it needs the owner's
  way of getting sanitised data.
- No signed iOS or Android release build; no staging environment for the new
  services; branch protection specified, not applied.
- No cutover: each needs the owner's explicit approval, verified data
  reconciliation, recovery testing and a controlled deployment.
