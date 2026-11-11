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
- Unit, integration, contract and parity tests; CI workflow.

Not done, and not claimed:

- No signed iOS or Android release build has been produced.
- No staging environment exists yet for the new services.
- The CI workflow and the container images have not run on GitHub (the branch
  has not been pushed).
- Branch protection for the migration branch is specified, not applied.
- Every domain other than the school slice is still served only by the
  existing application.
