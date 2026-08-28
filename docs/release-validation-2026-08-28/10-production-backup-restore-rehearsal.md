# Production backup and restore rehearsal — BACKUP-01

**Result:** PASS on 2026-08-28. A listed production backup was restored into
an isolated DigitalOcean Managed PostgreSQL cluster, brought to the deployed
schema, and exercised through the application before the temporary cluster was
deleted. The production cluster was never written to or reconfigured.

## Source and recovery point

| Field | Observed value |
|---|---|
| Production cluster | `edify-production-fra` (`5c96f186-d354-43b9-ade2-e021f9470528`) |
| Engine / region | PostgreSQL 17 / `fra1` |
| Status during rehearsal | `online` |
| Listed backup used | `2026-08-28 02:43:30 UTC` |
| Listed backup size | 0.319480 GiB |
| Retained listed backups | 8 daily recovery points, 2026-08-21 through 2026-08-28 |
| Rehearsal started | `2026-08-28 10:49:19 UTC` |
| Observed recovery-point age at start | 8h 05m 49s |

The recovery point was selected explicitly from `doctl databases backups`;
it was not inferred from a plan, feature flag, or YAML declaration.

## Isolated restore

DigitalOcean created `edify-restore-rehearsal-20260828`
(`9cc47ab8-2906-4177-aa33-03735433dc85`) from that timestamp. The cluster-create
event was emitted at `10:49:19 UTC` and master promotion at `10:53:47 UTC`:
an observed infrastructure restore time of **4m 28s**. The fork contained both
the expected `defaultdb` and application database `edify`.

The restored backup preceded the current release and correctly exposed two
unapplied recovery migrations:

- `budget.0012_alter_costcatalogue_kind`
- `monthly_work_plan.0007_monthlybudgetsubmissionsnapshot_country_funding_shortfall_and_more`

The pre-migration application smoke therefore caught a real incompatibility on
`/todos` (`regional_standard_ceiling` absent). Applying only those governed
migrations to the isolated copy completed in **201 seconds**. This is evidence
that the recovery procedure includes release migration, not evidence of a
damaged backup.

## Post-migration verification

`scripts/restore_smoke.py` then connected to the restored `edify` database and
completed in 259 seconds:

- 13 of 13 sequences were at or ahead of their owned columns;
- anonymous access was redirected to `/login`;
- 9 active accounts covered Accountant, Admin, CCEO, Country Director, HR,
  Impact Assessment, Program Lead, Project Coordinator, and RVP roles;
- `/dashboard`, `/my-plan`, `/schools`, `/todos`, `/analytics`,
  `/system-health`, `/settings`, and `/notifications` all returned HTTP 200 to
  a signed-in permitted role;
- the tamper-evident audit chain walked **1,713 of 1,713** rows with no break.

The measured recovery components total **12m 08s** (fork 4m28s + migrations
3m21s + application verification 4m19s), excluding deliberate operator review
between stages. No credentials, account addresses, or row data are recorded in
this artifact.

## Cleanup and safety

The rehearsal cluster was purpose-created, its exact ID was re-read before
cleanup, and it was deleted after the evidence passed. The production cluster
and its retained backups remain. This artifact and
`evidence-backup-restore.json` are the durable restore evidence; the temporary
copy was not retained because it contained production data and incurred cost.

## Verdict

BACKUP-01 is closed for recoverability: automated recovery points exist and a
real one has been restored and application-tested. The observed daily recovery
point was 8h05m old at rehearsal start, so business ownership must explicitly
accept that measured data-loss window or configure/verify a tighter objective.
Repeat this rehearsal after database-engine upgrades and at least quarterly.
