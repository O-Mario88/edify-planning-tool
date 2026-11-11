# 3. Production database protection

The production database holds real, actively used data. The migration is
developed without touching it. This document lists each protection, where it
is enforced, and the test that proves it. A protection that exists only as a
sentence is marked as such.

## 3.1 What was and was not touched in this assignment

- Production was not connected to, read, or written. No production secret was
  read or used.
- The only databases used were on the developer machine: `edify_gorn_dev` and
  `edify_gorn_test`, both built by the existing application's migrations with
  its synthetic demo seed.
- No existing migration was changed and none was added. The existing
  application's settings and database access are unchanged.

## 3.2 Enforced in code

| Protection | Where | Proven by |
|---|---|---|
| The gateway cannot start as a production process | `config.Load` returns `ErrProductionNotApproved` for `EDIFY_ENV=production` | `TestLoadRefusesProduction` |
| The gateway never reads `DATABASE_URL` (the existing application's variable), only `EDIFY_DATABASE_URL` | `internal/config` | `TestLoadIgnoresTheExistingApplicationsDatabaseURL` |
| A database URL that looks like production is refused before any connection, in every environment, even if allow-listed | `dbguard.CheckDSN`: built-in markers `edify-production-db`, `edifyplanning.app`, plus `EDIFY_DB_PRODUCTION_MARKERS` | `TestCheckDSN` |
| Development and test may connect only to this machine | `dbguard.CheckDSN` (loopback, unix socket, or explicit allow-list), fallback hosts included | `TestCheckDSN` |
| Staging may connect only to an explicitly named host, over TLS | `config.Load`, `dbguard.CheckDSN` | `TestLoadValidation`, `TestCheckDSN` |
| Staging refuses a database role that is a superuser or can write to the existing tables | `dbguard.VerifyIdentity` on the first connection | `TestStagingIdentityCheckAcceptsOnlyTheReadOnlyRole` |
| The connected database's own name is checked against the production markers | `dbguard.VerifyIdentity` | unit path of `VerifyIdentity` |
| Every gateway session is read-only | pool runtime parameter `default_transaction_read_only=on` | `TestGatewayRoleCanNeitherWriteNorReadSecrets` |
| The gateway contains no migration, DDL or write statement | no such code exists; a source scan fails the build if one appears | `TestGatewaySourcesContainNoSchemaChanges` |
| No automatic migration in any start-up path | the binary has no migration code; the existing application already migrates only in its pre-deploy job | same test |
| A refusal never prints the database password | `CheckDSN` does not echo a URL it could not parse | `TestCheckDSN` |
| The analytics worker cannot reach a database | no driver installed; refuses to start with database settings | `test_no_database_driver_is_a_dependency_or_an_import`, `test_the_worker_refuses_to_start_with_database_settings` |
| Integration tests cannot be aimed at a shared database | they require a local host and a database name ending in `_test` | verified by running them against `edify_pm`: refused |
| The role script cannot be run on production | `apply-roles.sh` requires a non-production `EDIFY_ENV`, refuses production markers, and outside staging refuses any non-local host | verified by running all three refusals |
| The mobile app cannot be pointed at production | `loadEnvironment` refuses the production hosts and any environment other than development or staging | `environment.test.ts` |
| CI cannot connect to production | `platform-ci.yml` holds no secret and no production address; its only database is a service container | by inspection of the workflow |

## 3.3 Enforced in the database

`platform/deploy/db/roles.sql` creates two roles and changes nothing else:

- `edify_gateway_ro` (no login): `SELECT` on exactly the columns the gateway's
  queries name. Password hashes, MFA secrets, reset tokens, lockout columns
  and refresh tokens are not readable through it.
- `edify_identity_rw` (no login, `identity_roles.sql`, 2026-11-11): signing in
  moved to Go, so this role grants exactly the existing sign-in's columns —
  see [08-sign-in.md §8.2](08-sign-in.md#82-what-it-writes-and-how-that-is-held).
- `edify_gateway` (login): member of the above, `default_transaction_read_only`
  set on the role.

Proven against a real database: update, delete, insert, create table, alter
table, reading an ungranted table, switching the session out of read-only and
then writing, changing an account's roles, email, superuser flag or
second-factor enrolment, rewriting or deleting audit rows, and deleting
sessions or accounts, are each refused.

Migration permission stays with the existing application's owner role. When a
Go module is approved to write, it gets a separate role with `INSERT`/`UPDATE`
on the named tables only, never DDL, and that grant is its own reviewed change.

## 3.4 Needs infrastructure (not yet in place)

These cannot be done from this repository and are not claimed:

1. **Network**: a firewall or trusted-sources rule on the production database
   cluster that admits only the production application. Staging and developer
   addresses must not be on it.
2. **Credentials**: the production database must have no user shared with
   staging or development. The staging cluster is a different cluster with its
   own users.
3. **Secrets**: staging and production secrets in separate stores, with no
   person or pipeline holding both by default.
4. **The exact production hostname** added to `EDIFY_DB_PRODUCTION_MARKERS` in
   the staging and CI configuration, so the refusal does not rest on the
   cluster name alone.

## 3.5 Realistic data

Synthetic data first: the demo seed (700 schools, every role) is what
development, tests and CI use.

When realistic volume or shape is needed:

1. Take a backup through DigitalOcean's managed backup, restored by the
   platform into a **new, separate cluster**. Never `pg_dump` from a developer
   machine against production.
2. Sanitise in that new cluster before anyone else connects: replace names,
   emails, phone numbers and contact fields; clear password hashes, MFA
   secrets, refresh tokens, push subscriptions and notification bodies; clear
   evidence and document storage keys or point them at an empty bucket.
3. Check the sanitisation with queries that must return zero rows, and record
   the check.
4. Only then grant the staging services access.

This procedure needs explicit approval each time it is used.

## 3.6 Schema

- The gateway maps onto the existing tables as they are. No table, column,
  index, constraint or trigger was added or changed.
- `TestExistingSchemaContract` lists every column the gateway reads and the
  type it expects. It runs against the schema built by the existing
  migrations at the commit under test, so a migration on `main` that changes
  one of those columns fails this test, not a query in staging.
- If a new capability needs storage of its own, the first option is a separate
  auxiliary database owned by the new backend. A change to the existing schema
  is a separate proposal with a risk assessment, approval, and a tested backup
  and recovery, and is not authorised by this work.

## 3.7 Writes, when they come

No dual writes, ever. For each table:

(Sign-in is the one place where, on development and test databases, both
systems write the same columns, under the same row locks and the same
policy, while the web's sign-in page still uses the existing application.
Production cutover moves the web's sign-in to Go in the same release, so
step 3 below holds: 08 §8.4.)

1. The existing application is the only writer.
2. The Go module is built and compared in **shadow**: it computes what it
   would write, on a restored copy, and the result is compared with what the
   existing application wrote.
3. On approval, writes for that table move to Go in one step, and the existing
   application's write path for it is switched off in the same release.
4. Rollback is switching back, which is why the schema does not change.

## 3.8 The Cluster Leader Portal's own schema (2026-11-10)

The owner chose a **Go-owned schema** for the portal's records (cluster
leadership assignments and their history; later its invitations, attendance,
minutes and action items). They are new records the existing application
never writes, so there is no dual write.

- **Where:** schema `cluster_leadership` in the same database, created by
  `deploy/db/cluster_roles.sql` (run by `apply-roles.sh`), owned by the
  NOLOGIN role `edify_cluster_owner`. The owner role holds no privilege on any
  existing table: a migration cannot read, alter, index or write one
  (`TestClusterOwnerCannotTouchTheExistingTables`).
- **Migrations:** `internal/clusterlead/schema/migrations/*.sql`, applied only
  by `clusterctl migrate --confirm-database=<name>`, as the owner role, one
  transaction per file, refusing an edited migration (checksums) and any
  database other than the one confirmed. The gateway never migrates; it reads
  the applied version and answers "not set up on this server yet" until it
  matches. Every migration passes a lint (`schema.Lint`): only `CREATE TABLE`,
  `CREATE INDEX`, `ALTER TABLE`, `COMMENT ON` and `GRANT … TO edify_cluster_rw`
  on `cluster_leadership` objects; no drop, truncate, delete, role change,
  code, or reference into the existing schema.
- **No foreign keys into the existing tables** (a foreign key would add a
  trigger to them); Go checks the cluster and the account on every write.
- **Writes:** the gateway's role is still read-only by default; a portal
  write opens a read-write transaction on purpose and can reach only the
  tables `edify_cluster_rw` was granted. Assignments can be inserted and
  updated, never deleted; their history can only be appended to
  (`TestGatewayWritesOnlyThePortalsOwnTables`). `TestGatewaySourcesContainNoSchemaChanges`
  now allows writes and DDL only inside `internal/clusterlead`, and only on
  `cluster_leadership` objects.
- **Production:** none of this exists there. Creating the schema and running
  `clusterctl migrate` on production is a separate step that needs the
  owner's approval.
- **The role:** `ClusterLeader` was added to the existing role list with no
  web permission. Its four choice-only Django migrations
  (`accounts 0040`, `acting 0002`, `audit 0009`, `help_center 0011`) issue no
  SQL (`sqlmigrate` shows `(no-op)` for each).

## 3.9 The School Loan Application Portal's own schema (2026-11-11)

The portal's records (applications schools submit through the public form,
their timeline and follow-ups, the lender-delivery outbox, lender access
links, codes and sessions, school invitation links, and each Loan Partner's
receiving address) are new records the existing application never writes.
They follow the Cluster Leader pattern (§3.8), which the owner chose for
Go-owned records:

- **Where:** schema `school_loans`, created by `deploy/db/loan_roles.sql`
  (run by `apply-roles.sh`), owned by the NOLOGIN role `edify_loans_owner`,
  which holds no privilege on any existing table. The gateway reaches it
  through `edify_loans_rw`, table by table; event, follow-up and
  channel-history tables are insert-only.
- **Migrations:** `internal/loans/schema/migrations/0001-0003`, applied only by
  `schemactl migrate --schema=school_loans --confirm-database=<name>`. The
  migration mechanics (lint, checksums, ledger, owner role, advisory lock)
  moved to `internal/ownedschema`, shared by both Go-owned schemas;
  `clusterctl` still works for `cluster_leadership`.
- **What it reads, never writes:** the Partner Directory's Loan Partners
  (`partner`) and their lenders (`bt_mfi_organization`, `bt_mfi_membership`),
  the School Directory (`school`, `district`, `sub_county`, `parish`), and, for
  a school's history, `bt_loan_application`, `bt_mfi_loan` and
  `bt_loan_purpose` — column by column in `loan_roles.sql`. The existing loan
  workflow (the web form at `loan-applications/apply`, the MFI portal, the
  loan ledger and its targets) keeps working exactly as it does.
- **No foreign keys out of the schema**; Go checks partners, lenders and
  schools on every write. School matching never creates a directory school.
- **Guards:** `TestGatewaySourcesContainNoSchemaChanges` now allows writes only
  inside `internal/clusterlead` (on `cluster_leadership`) and `internal/loans`
  (on `school_loans`), and DDL only in `internal/ownedschema` on a schema's own
  migration ledger; planted violations of both kinds were caught.
  `TestTheGatewayRoleCannotWriteTheExistingLoanRecords` proves the gateway's
  role is refused on `partner`, `bt_mfi_organization`, `bt_loan_application`
  and `school`.
- **Mail:** nothing is sent from development except to a file mailbox
  (`EDIFY_DEV_MAILBOX_DIR`, refused outside development and test). Staging
  needs `EDIFY_SMTP_ADDR` (TLS only), `EDIFY_MAIL_FROM` and an https
  `EDIFY_PUBLIC_BASE_URL`; the production site is refused as a base URL.
- **Production:** none of this exists there. Creating the schema, migrating it
  and configuring mail on production each need the owner's approval, a
  backup and a recovery plan.
