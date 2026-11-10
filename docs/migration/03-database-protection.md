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
  and refresh tokens are not readable.
- `edify_gateway` (login): member of the above, `default_transaction_read_only`
  set on the role.

Proven against a real database: update, delete, insert, create table, alter
table, reading `user.password`, reading `mfa_secret`, reading `refresh_token`,
reading an ungranted table, and switching the session out of read-only and
then writing, are each refused.

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

1. The existing application is the only writer.
2. The Go module is built and compared in **shadow**: it computes what it
   would write, on a restored copy, and the result is compared with what the
   existing application wrote.
3. On approval, writes for that table move to Go in one step, and the existing
   application's write path for it is switched off in the same release.
4. Rollback is switching back, which is why the schema does not change.
