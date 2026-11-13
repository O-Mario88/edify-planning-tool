# 61. A shadow base the roles files apply to cleanly

Every save is proved on shadow copies of the development database (26). The
copies need the gateway's roles, so the recipe is `copies.sh base`, then
`platform/deploy/db/apply-roles.sh` on the base, then `copies.sh fresh`. On a
fresh base the second step failed, and agents 36 and 37 had to repair each
base by hand (36 dropped the dumped `gateway_*` schemas, 37 reset owners to
development's) before a proof could start.

## 61.1 What was wrong

`copies.sh base` dumped with `pg_dump --no-owner --no-privileges`. With
`--no-owner` every object in the base belongs to the person who ran the dump,
including the three Go-owned schemas, which in development belong to NOLOGIN
owner roles:

| Schema | Owner in development | Owner in the old base |
|---|---|---|
| `gateway_read` (the Decision Log and evidence-kind views) | `edify_audit_view_owner` | the dumping user |
| `cluster_leadership` (Cluster Leader Portal tables) | `edify_cluster_owner` | the dumping user |
| `school_loans` (School Loan Application Portal tables) | `edify_loans_owner` | the dumping user |

`decision_log_roles.sql` does `SET ROLE edify_audit_view_owner` and
`CREATE OR REPLACE VIEW gateway_read.decision_audit`; that role has no rights
in a schema it no longer owns, so `apply-roles.sh` stopped there:

```
psql:…/decision_log_roles.sql:109: ERROR:  permission denied for schema gateway_read
```

Nothing after it ran: no evidence-kind view, no `gateway_lock` functions, no
`gateway_money` function, no activity writer grants.

Dropping the schemas (agent 36's repair) is not a general answer: the
`cluster_leadership` and `school_loans` schemas hold rows (made by
`schemactl migrate`, not by the roles files), and dropping them loses that data
from the copy.

## 61.2 The change

`copies.sh base` now dumps with `pg_dump --no-privileges` only, so the base
keeps the source's owners (every role is cluster-wide, and the copies are made
on the same server). Grants are still left out: `apply-roles.sh` makes them from
the repository's roles files, so a proof runs on the grants the branch ships,
not on whatever development happens to hold. `copies.sh fresh` uses the base as
a template, which carries owners and grants into both copies. Nothing else in
the script changed (names still checked, the source still only read).

The manual repair steps in agents 36's and 37's notes are no longer needed.

## 61.3 The test script

`platform/backend/cmd/shadow/copies_test.sh` needs your own three copies named
(the coordinator's default names are refused):

```
EDIFY_SHADOW_BASE=edify_shadow_s22_base EDIFY_SHADOW_A=edify_shadow_s22_a \
  EDIFY_SHADOW_B=edify_shadow_s22_b platform/backend/cmd/shadow/copies_test.sh
```

It makes the base with `copies.sh base`, then checks:

1. every schema, relation and function in the base has the source's owner;
2. every table's row count matches the source's. The source is live (people
   sign in while it is dumped), so each table is counted before and after the
   dump: a table that did not move must match exactly, and one that moved must
   hold a count between the two;
3. `apply-roles.sh` runs clean on the base, twice (the second run must be clean
   too);
4. what the roles files make has the right owner (`gateway_read.decision_audit`,
   `gateway_read.activity_evidence_kind`, schema `gateway_lock`,
   `gateway_lock.lock_school`, `gateway_lock.lock_cluster`,
   `gateway_money.withdraw_unmoved_advances`), and `edify_gateway_ro` reads the
   audit view and school columns but cannot UPDATE `school` or INSERT into the
   view;
5. after `copies.sh fresh`, both copies have the base's owners and pass 4.

## 61.4 Results (2026-11-13, on edify_shadow_s22_*)

With the fixed script (`agent42_copies_test3.txt`): exit 0, 39 checks
`ok`, `all checks passed`. In full: base owners equal edify_gorn_dev's (484
objects); 422 tables exactly, 3 written during the dump within their range
(`audit_log`, `domain_event_log`, `interaction_event`); `apply-roles.sh` first
and second run clean; every owner and grant check on the base and both copies
`ok`.

The same test run against the old `copies.sh` from
`feature/edify-go-rn-migration` (`--no-owner`): exit 1, `27 check(s) failed`,
including the three schema owners, `apply-roles.sh first run exited non-zero`
with the `decision_log_roles.sql:109` error above, and every object the later
roles files make missing from the base and both copies. So the test catches the
defect it was written for.

## 61.5 Left

- Production restores are unaffected (`scripts/migrate_to_managed_cluster.sh`
  already keeps owners and privileges; `docs/runbooks.md` warns against
  `--no-owner`).
- Shadow bases made before this change (`edify_shadow_s19/s21/s25_*` and the
  coordinator's `edify_shadow_base`) were repaired by hand and were not touched
  here. Remake them with the fixed script when next needed.
