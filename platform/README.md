# Edify platform

The new architecture, developed beside the existing Django application and
isolated from production. Start with
[docs/migration/README.md](../docs/migration/README.md).

| Folder | What |
|---|---|
| `proto/` | Protocol Buffer contracts (buf) |
| `backend/` | Go gateway and modules |
| `workers/analytics/` | Python analytics worker (internal gRPC, no database) |
| `mobile/` | React Native app (Expo, TypeScript) |
| `deploy/db/` | Least-privilege database roles |
| `tools/` | Pinned generators; parity check against the existing API |

Setup, checks and staging:
[docs/migration/05-environments-and-staging.md](../docs/migration/05-environments-and-staging.md).

Three rules that the code enforces and a change must not weaken:

1. The gateway reads its database only from `EDIFY_DATABASE_URL`, refuses
   anything that looks like production, and refuses to run as production.
2. Rules live in Go. The Python worker and the app decide nothing.
3. No existing identifier is re-issued and no existing table is altered.
