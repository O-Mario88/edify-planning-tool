# Staging step: the `field_routes` schema (Verify Location and offline GPS capture)

**Status: prepared, not run.** Nothing here has touched staging. It runs only after the owner approves it in writing (sign-off at the end), by an operator holding the staging owner credentials. Production is never involved: the scripts refuse a production environment, a URL that looks like the production cluster, and (staging) any connection without TLS.

Brief and decisions: `next-offline-gps-capture.md`. Test results: `offline-gps-capture-test-report.md`. Staging environment and gateway settings: `05-environments-and-staging.md` §5.3.

## What it changes, and what it never touches

| Changes on the staging database | Never touched |
|---|---|
| Creates the schema `field_routes`, owned by a new `NOLOGIN` role `edify_routes_owner` | any table, column, index, constraint or row of the existing application (`school`, `school_geo_point`, `activity`, `user`, …) |
| Creates the `NOLOGIN` role `edify_routes_rw` and grants it to `edify_gateway` | existing roles' rights on existing tables |
| Migration `0001_location_verification`: `location_report`, `verified_location` | School IDs, Activity IDs, coordinates of record |
| Migration `0002_location_capture`: `location_capture`, `school_location`, `location_change` | the existing application's migrations |
| Grants on those five tables to `edify_routes_rw` only | |

The migration lint (run in CI and at apply time) refuses any `DROP`, `DELETE`, `TRUNCATE`, role change, code, or reference outside `field_routes`. Each migration runs in its own transaction as `edify_routes_owner`, which holds no right on the existing tables; the ledger `field_routes.schema_migration` records each with its checksum.

## Before starting

- [ ] Owner approval signed below.
- [ ] Staging exists as in §5.3 (cluster `edify-staging-pg-fra` or its successor), separate from production.
- [ ] The operator's shell has **only** staging credentials: no production URL in the environment or history. `DATABASE_URL` is never read by these tools; unset it anyway.
- [ ] `EDIFY_DB_PRODUCTION_MARKERS` set to the production cluster's hostname (an extra refusal on top of the built-in markers).
- [ ] The gateway build to deploy contains commit `cd8117828` or later of the migration work (location capture). Until it is deployed the old gateway simply ignores `field_routes`.
- [ ] A fresh on-demand backup (or fork) of the staging database is taken and its name noted: ________________

## Steps

Set once in the operator shell (values from the staging secret store, never production's):

```bash
export EDIFY_ENV=staging
export EDIFY_ADMIN_DATABASE_URL='<staging owner URL, sslmode=require>'
export EDIFY_MIGRATE_DATABASE_URL="$EDIFY_ADMIN_DATABASE_URL"
export EDIFY_DB_ALLOWED_HOSTS='<staging cluster hostname, exactly>'
export EDIFY_DB_PRODUCTION_MARKERS='<production cluster hostname>'
export STAGING_DB='<staging database name>'
```

**1. Record the school coordinates before anything** (read-only; compared again at step 6):

```bash
psql "$EDIFY_ADMIN_DATABASE_URL" -Atc "SELECT count(*), md5(string_agg(id || ':' || coalesce(latitude::text,'') || ',' || coalesce(longitude::text,''), ';' ORDER BY id)) FROM school"
psql "$EDIFY_ADMIN_DATABASE_URL" -Atc "SELECT count(*), md5(coalesce(string_agg(school_id || ':' || latitude || ',' || longitude, ';' ORDER BY school_id), '')) FROM school_geo_point"
```

Write both lines down: ________________

**2. Roles and the empty schema** (idempotent; safe to re-run):

```bash
platform/deploy/db/apply-roles.sh
```

**3. See where the schema stands:**

```bash
cd platform/backend && go run ./cmd/schemactl status
```

Expected for `field_routes`: `applied version 0, this build needs 2`.

**4. Apply the migrations:**

```bash
go run ./cmd/schemactl migrate --schema=field_routes --confirm-database="$STAGING_DB"
```

Expected:

```
applied field_routes 0001 0001_location_verification
applied field_routes 0002 0002_location_capture
```

It refuses (and changes nothing) if `--confirm-database` is not the database it is connected to, if the schema is not owned by `edify_routes_owner`, or if a recorded checksum differs from the build's.

**5. Check what was made:**

```bash
psql "$EDIFY_ADMIN_DATABASE_URL" -Atc "SELECT version, name FROM field_routes.schema_migration ORDER BY version"
psql "$EDIFY_ADMIN_DATABASE_URL" -Atc "SELECT tablename FROM pg_tables WHERE schemaname = 'field_routes' ORDER BY 1"
psql "$EDIFY_ADMIN_DATABASE_URL" -Atc "SELECT has_table_privilege('edify_gateway','field_routes.location_capture','INSERT'), has_table_privilege('edify_gateway','public.school','UPDATE'), has_table_privilege('edify_gateway','public.school_geo_point','INSERT'), has_table_privilege('edify_routes_owner','public.school','SELECT')"
```

Expected: versions 1 and 2; tables `location_capture, location_change, location_report, schema_migration, school_location, verified_location`; privileges `t|f|f|f` (the gateway writes only `field_routes`; the owner role cannot even read `school`).

**6. Prove nothing else moved:** run the two step-1 queries again; both lines must be identical.

**7. Deploy the gateway build** (per §5.3), then:

- [ ] `/readyz` is green.
- [ ] The gateway log shows no `field routes schema not ready` warning after the first location request.
- [ ] With a **staging test account** (never a real staff account's real schools without the owner's say): open a school profile, see Location & Directions with its version and verified facts; capture a test school's location from the staging app build; see it pending or accepted per the policy; review it as a staging Program Lead; see the planner use the new point.
- [ ] Re-run step 6: the existing application's coordinates are unchanged.

## If something goes wrong

- **Steps 2–4 fail or are refused:** nothing is half-applied (each migration is one transaction). Read the message; fix the cause (wrong database name, missing role grant, TLS); re-run. Do not edit a migration file: a changed checksum is refused on purpose.
- **The new gateway misbehaves:** redeploy the previous gateway build. It does not read `field_routes`; the planner and profiles return to the School Directory's points. The new tables stay, unused.
- **The schema itself must go:** not provided here. The lint forbids `DROP` in migrations; removal is a separate, owner-approved operator action with its own backup, never improvised.
- **Restore** from the backup taken before starting only if the existing application's data were affected, which step 6 checks they are not.

## After

- [ ] Record in this file: date, operator, backup name, the outputs of steps 3–6.
- [ ] Staging app build (EAS `preview`, `EXPO_PUBLIC_EDIFY_ENV=staging`) given to testers; offline capture tried on real Android phones and an iPhone (the gaps in the test report).
- [ ] Routing provider on staging (OSRM or Google) is a separate decision; without one the planner shows straight-line figures, labelled as such.

## Rehearsal (2026-11-14, local copy, not staging)

Run on a throwaway local database holding only the existing application's `public` schema copied from the test database (700 schools), as `EDIFY_ENV=development` because staging insists on TLS, which a local database lacks. Every step as written:

| Step | Result |
|---|---|
| 1 before | `700 | d0d5c242…` and `0 | d41d8cd9…` |
| 2 roles | ran clean, exit 0 |
| 3 status | `field_routes: applied version 0, this build needs 2` |
| 4 wrong `--confirm-database` | refused: connected to "edify_routes_rehearsal2" but --confirm-database is "edify_gorn_test"; nothing applied |
| 4 migrate | applied 0001, 0002 |
| 4 again | `field_routes is up to date (version 2)` |
| 5 | versions 1, 2; the six tables; privileges `t|f|f|f` |
| 6 after | identical to step 1 |
| staging without `sslmode` | refused: staging connections must use TLS |
| `EDIFY_ENV=production` | refused: production cutover has not been approved for this build |

Found while preparing this:

- **The staging TLS guard let a plain-text fallback through.** A URL without `sslmode` (or with `sslmode=prefer`) gives a TLS config *and* a plain-text fallback; the guard only checked the first. Fixed in `internal/dbguard`: staging now refuses any URL that may fall back to plain text. This guard also protects the gateway and `clusterctl` at startup. Tests added.
- **CI would have failed since the Verify Location commit:** the gateway-wide scan for write statements did not yet list `routeplan` as a writer of its own schema. Added, limited to `field_routes.*`, as `clusterlead` and `loans` are.

The rehearsal databases were dropped afterwards.

## Owner approval

I approve running the steps above on the **staging** database named ______________ only.

Name: ______________  Date: ______________
