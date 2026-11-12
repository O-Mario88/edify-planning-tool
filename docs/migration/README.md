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

The code is under [`platform/`](../../platform/README.md).

## Where things stand

Done on this branch (initial assignment):

- Audit and baseline.
- Contracts with lint, compatibility check and reproducible generation.
- Go gateway: health checks, structured errors, request tracing, authentication
  against the existing identity system, production-database guard, read-only
  database role.
- One vertical slice: an authenticated officer's own schools, read from the
  existing `school` table, identical to what the existing API returns.
- Python analytics worker called by the gateway over internal gRPC.
- React Native (Expo) app foundation: sign-in, session, My Schools.
- Web frontend decided (owner, 2026-11-12): Next.js, TypeScript and Tailwind CSS
  for browsers, a client of the same Go gateway (02, 2.10; plan M15). Not
  started yet.
- Unit, integration, contract and parity tests; CI workflow.

Not done, and not claimed:

- No signed iOS or Android release build has been produced.
- No staging environment exists yet for the new services.
- The CI workflow and the container images have not run on GitHub (the branch
  has not been pushed).
- Branch protection for the migration branch is specified, not applied.
- Every domain other than the school slice is still served only by the
  existing application.
