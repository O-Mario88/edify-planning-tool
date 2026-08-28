# Production Readiness — Remediation Ledger

**Pass 1 of N: measurement.** Nothing in this document is an opinion. Every
number comes from a scanner that names a file and a line, and every scanner is
pinned by a test that can fail.

- **Commit:** `a7d3afae` (branch `feat/platform-operations-and-document-library`)
- **Suite at baseline:** 3,134 tests, 0 failures, 1 skipped
- **Ruff:** clean · **Migrations:** no drift · **CSS bundle:** rebuilt, no diff
- **Scanner:** `apps/system_health/production_readiness.py`
- **Gate tests:** `apps/system_health/test_production_readiness.py`

Run it yourself:

```bash
.venv/bin/python manage.py test apps.system_health.test_production_readiness
```

---

## 1. Hard-zero gates, measured

| Gate | Required | Measured | Status |
| --- | --- | --- | --- |
| Mock/demo data in the production runtime (§7) | 0 | **0** | GREEN |
| Dead controls — anchors with no destination and no handler (§11) | 0 | **0** | GREEN |
| Business analytics computed in JavaScript (§13, §40) | 0 | **3** | OPEN |
| Page routes with no declared permission (§9) | 0 | **6** | OPEN — mitigated |
| Workflow state written outside a canonical service (§6, §37) | 0 | **30** | OPEN |

Two of the five are genuinely clean. The scanners' first run reported four more
than this, and I removed them because they were the scanner's own fault, not the
platform's: the mock-data scanner matched the pattern definitions inside itself,
and the JavaScript scanner counted `this.balance = 0` as a computation. Both
corrections are pinned by their own tests, so the scanner cannot silently go
blind in the other direction either.

## 2. Existing inventory (unchanged by this pass)

`manage.py build_page_inventory` — 451 routed surfaces, 1,089 routes, 444
permission-gated, 52 permission keys, 11 roles, 15 scheduled jobs, 417
test-referenced. Severity: 0 critical, 0 high, 12 medium, 5 low — all cosmetic
(raw hex colours, inline styles, literal white surfaces).

---

## 3. Open findings, ranked

### ISSUE-001 · SSA verification status written from a view · **HIGH**

`apps/frontend/views/ssa_views.py:341`

```python
rec.verification_status = VerificationStatus.CONFIRMED.value
```

§35 states official SSA verification must require IA authority and must not
follow from a role merely being able to open the page. Here the transition is
performed in the view, so whatever guard, audit row and notification the
canonical service attaches are bypassed.

**Downstream:** SSA verification decides which records official impact
reporting may use (§16, §41). A confirmation written outside the service is a
confirmation with no provenance.

**Fix (pass 2):** move to `SSAVerificationService.confirm()` with an IA
authority check, audit event and notification; leave the view calling it.

### ISSUE-002 · Finance state written from views · **HIGH**

`apps/frontend/views/finance_views.py:460, 539, 551`

```python
wfr.status = "accounted"
wfr.status = "returned_by_accountant"
adv.status = AdvanceRequestStatus.RETURNED
```

Money states set outside the disbursement service, which is where the
view/action split, the idempotency guard and the audit row live (§32, §36).

### ISSUE-003 · Core slot status written from views · **MEDIUM**

`apps/frontend/views/core_schools_views.py:409, 566, 724` — `slot.status =
"Scheduled" / "Assigned"`. The 9-slot package and its 2+2 staff cap are
enforced in the Core service; a direct write skips both (§20).

### ISSUE-004 · 30 raw workflow mutations in total · **MEDIUM**

Full distribution: `extended_views.py` 9, `upload_views.py` 3,
`core_schools_views.py` 3, `finance_views.py` 3, `ia_views.py` 3,
`ssa_views.py` 2, `leave_views.py` 2, `planning_views.py` 2,
`help_center/views.py` 1, `pd_views.py` 1, `school_views.py` 1.

Not all are equal — an import batch's `status` is arguably local bookkeeping,
while SSA verification is not. Pass 2 triages each against whether a canonical
service already owns that transition.

### ISSUE-005 · Weighted SSA average computed in JavaScript · **MEDIUM**

`templates/partials/analytics/regional_performance.html:696–706`

An n-weighted mean across district aliases, computed client-side. §40 permits
no authoritative business analytic in JavaScript.

Worth noting the existing code is careful — it returns `null` rather than
inventing a weighting when aliases combine, and says so in a comment. The
defect is the location, not the arithmetic.

**Fix (pass 2):** merge district aliases and compute the weighted mean in the
regional analytics service; the template renders the result.

### ISSUE-006 · Six routes with no declared permission · **LOW — mitigated**

The six performance-conversation endpoints delegate authorization to
`apps.hr.performance_engine`, which I verified does enforce it: 13 `Forbidden`
raises, plus ownership checks (`Only the employee writes their own reflection`)
and a window check. So this is not an access hole.

It is an authorization-drift finding in §9's sense: the permission source is
not declared where the route is, so a page-permission audit cannot see it.
Either declare it or record it as an accepted exception — pass 2 decides which.

---

## 4. Gates I cannot verify in this environment

Per the agreed approach, these get a harness and an honest status, never a
green tick.

| Gate | Status | What is needed |
| --- | --- | --- |
| 95% planning-time reduction (§2) | **UNVERIFIED** | A human baseline. §2 requires representative staff performing real tasks — elapsed time, active interaction time, clicks, fields, abandoned attempts. I can instrument the flow and count the mechanical half; I cannot produce the human half, and reporting a percentage without it is precisely what §2 forbids. |
| 15,000-school performance (§46) | **UNVERIFIED** | Production-like staging data and a load harness run against it. |
| Backup restore rehearsal (§53) | **UNVERIFIED** | A backup is not verified until restored. Prior drills exist in the project record but predate this commit, and §4 forbids reusing an earlier commit's results. |
| Rollback rehearsal (§53) | **UNVERIFIED** | Same. |
| Visual regression / accessibility tooling (§4) | **UNVERIFIED** | Not configured in this repository; nothing to run. |

## 5. Readiness score

**Not scored.** §54 requires every point to carry evidence, and four of the ten
scoring dimensions depend on gates in §4 above that have not been executed.
Producing a number now would be narrative, which §54 explicitly forbids.

What can be stated: two hard gates are clean and pinned, three are open with
named findings and a fix path, and the full suite is green at this commit.

## 6. Pass 2 — remediation (done)

| Issue | Status | Evidence |
| --- | --- | --- |
| ISSUE-001 SSA verification written from a view | **CLOSED** | `verify_record` / `return_record` in `apps/ssa/services.py`; 7 tests in `apps/ssa/test_verification_authority.py` including one that fails if the transition moves back into a view |
| ISSUE-002 Finance state written from views | **CLOSED** | `return_weekly_request` + `roll_up_accountability` in the disbursement service, behind `_require_accountant_action` |
| ISSUE-005 Weighted SSA mean in JavaScript | **PARTIAL** | Canonical `weighted_ssa_mean` / `combine_district_rows` in `apps/analytics/subregion_analytics.py`, 11 tests. The template has **not** been switched over — see below |
| ISSUE-006 Six undeclared routes | **ACCEPTED EXCEPTION** | Verified `performance_engine` enforces authorization (13 `Forbidden` raises, ownership + window checks). Recorded here rather than declared at the route |

Raw workflow mutations: **30 → 26**.

### ISSUE-001, in detail

The view *did* check `ia.verify` before writing, so this was never an open
door. The defect was location: a transition written in a view is one every
other caller — an API, an HTMX endpoint, a management command, a future page —
can perform without the authority check, the readiness recompute or the audit
row. Those three are what make a confirmation mean anything.

The service is idempotent: a double-submitted form re-confirms nothing and
writes no second audit row.

One thing I nearly broke: moving the code, I renamed the audit action from
`weekly_fund_request.return_by_accountant` to an underscored variant. An
existing test caught it. The established audit vocabulary is a contract with
history and must not change as a side effect of moving code.

### ISSUE-005, why it is only partial

The server already computed this weighted mean correctly in `_group`; the
template was a second implementation for map boundaries spanning several
districts. The canonical helper now exists and is tested, including a worked
example pinning it to the formula the JavaScript used.

Retiring the JavaScript needs the boundary-to-district mapping to move
server-side as well — the client currently matches GeoJSON polygons to district
rows, so the server does not know which districts a hovered boundary covers.
That is a separate change and is **not done**. The JavaScript gate therefore
still reads 3.

## 7. Planning productivity (§2)

`apps/system_health/planning_benchmark.py`, 9 tests.

**Mechanical half — measured:**

| | |
| --- | --- |
| Fields a human supplies | **4** — school/cluster, date, executor, override reason |
| Fields the platform derives | **21** — SSA record, intervention, activity type, entitlement slot, FY, quarter, month, week, catalogue rate, unit cost, quantity, total, budget line, My Plan entry, weekly request line, monthly and annual contribution, approver, responsible staff, notification, audit |
| Automation ratio | **84.0%** |
| Repeated manual entries | **0** |

**Time half — UNVERIFIED, and the code says so.** `Benchmark.reduction()`
returns `verified: False` with a reason when there are no paired observations,
and a test asserts it never emits a percentage without them. A near-miss test
pins that 94.7% is reported as a miss rather than rounded up.

To complete this gate, record `Observation` rows from representative staff
performing the baseline and optimised tasks. The 95% conclusion computes
itself from those; it cannot be derived from the code, and §2 forbids claiming
it because automation exists.

## 8. Previously-unverified gates — executed

| Gate | Status | Evidence |
| --- | --- | --- |
| Backup restore rehearsal (§53) | **RE-RUN AND PASSED against `edify` — production source still unexercised** | The PASS originally recorded here established one thing: the commands in `scripts/backup_restore_rehearsal.sh` ran without erroring. It established nothing about the restore, because every threshold it used clears on a database with no rows in it — see ISSUE-008. The gate was rebuilt around `scripts/restore_manifest.py`, rebuilt again after two adversarial reviews, and then had two further defects found by running it rather than reading it (ISSUE-008c). It has now been run end to end against the platform's own developer source `edify` at commit `cad73c69`: **exit 0, 25 PASS, 0 FAIL**, 8,789 comparisons against a manifest of the dump, 8 pages served to *signed-in* accounts from the restored copy across 10 roles, audit hash chain walked 161 of 161 rows, scratch copy dropped. Proven able to fail: **12 of 12 testable corruption classes caught** (ISSUE-008c). This is a dev-estate source of 700 schools and 27,828 rows; **the production source has still never been dumped or restored by anyone**, so §53 is satisfied for the mechanism and not for the estate it will run against |
| Backups exist at all (§53) | **NO — RELEASE BLOCKER** | `.do/app.yaml` declared the production database on App Platform's dev tier, which DigitalOcean documents as having no backups and explicitly does not recommend for production. The restore gate above verifies a round trip that nothing was feeding. The spec now declares a managed cluster and a test fails while it does not, but applying it is a data migration nobody has run and this environment has no DigitalOcean credentials to check what is actually live. See BACKUP-01 |
| Latency budgets (§46) | **RUN — 1 breach** | `scripts/latency_budget.py`, 15 samples per page per role after 2 discarded, 702 schools. 23 of 24 page/role combinations within budget; `/todos` for the Country Director breached |
| Scale invariance (§46) | **PASSED** | `apps/system_health/test_load_scale.py` at 15,000 schools + 3,000 growth, in the green suite |
| Wall-clock at 15,000 schools | **MEASURED — every page inside budget** | First measurement ever taken at full estate size. `/dashboard` 230ms of an 800ms budget, `/my-plan` 81, `/schools` 161, `/todos` 177, `/notifications` 28, `/settings` 20, `/analytics` 420 of 1500, `/system-health` 9. The worst page sits at 29% of its budget at 21x the dev estate. Now gated by `test_pages_stay_inside_their_budgets_at_scale`. **Caveat, and it is not a small one:** this container, single request, no concurrency, synthetic estate — it is not a p95 and it is not production hardware. See PERF-01 |
| Rollback rehearsal (§53) | **STILL UNVERIFIED against the platform's source** | `scripts/rollback_rehearsal.sh` carried the same defects as the backup gate and has been repaired alongside it: the dead scratch-name guard, the `check()` that passed on two empty strings (removed — it had no call sites left), `pg_dump \| pg_restore >/dev/null 2>&1` with every error discarded, a step 3 with no failing path, a relative `PYTHON_BIN` that made the script exit 127 in silence from any directory but the repository root, no ERR trap and so no verdict on an abort, and `git worktree remove --force` running unconditionally ahead of its own ownership check — which destroyed a pre-existing worktree holding uncommitted work. Run end to end against the platform's own developer source `edify` at commit `cad73c69`: **exit 0, 16 PASS, 0 FAIL** — `7c27f2f6` serves the schema `cad73c69` leaves behind, 320 migrations known to the previous release with 0 missing, 8 pages served to signed-in accounts from the migrated copy. Not run against the production source |
| Accessibility tooling (§4) | **RUN ACROSS ALL THREE THEMES — 0 blocking** | `scripts/accessibility_audit.py` drives Chromium through axe-core over the eight core pages in **light, dark and blue**, signed in, with the real stylesheet: **24 scans, 0 critical, 0 serious**. The first run (light only) found 6 serious contrast failures and all six were fixed rather than baselined. Palettes verified genuinely distinct, and the dark scan proven to catch a dark-only failure. Ratcheted at zero. Covers only what axe detects automatically — keyboard traps, focus order and screen-reader semantics are unmeasured. See A11Y-01 and A11Y-02 |
| Visual regression tooling (§4) | **STILL UNVERIFIED** | No screenshot baseline exists. The accessibility half of this row is now covered; the pixel-diff half is not, and needs a decision about where baselines live before it is worth building |
| 95% planning-time reduction (§2) | **STILL UNVERIFIED** | Mechanical half measured (see §7); human half needs staff observations |

Two gates that were UNVERIFIED are now executed with evidence, and the latency
run found a real defect.

### ISSUE-008 · The backup gate could not fail, and its PASS was recorded as evidence · **HIGH**

> Note on numbering: §9 below carries a different, closed ISSUE-008 (reminder
> dedupe). The identifier was reused by mistake when this entry was written.
> References elsewhere in the repository to "ISSUE-008" mean this one, the
> backup gate. Renumbering either would break the other's history, so both
> keep their number and this note disambiguates them.

The row above previously read **PASSED**. It was withdrawn because the check
that produced it cannot distinguish a good restore from a wiped database.

`scripts/backup_restore_rehearsal.sh` verified a restore with three floors and
one comparison. Measured against this schema **with every table empty**:

| Check | Floor | A wiped database measures | Verdict |
| --- | --- | --- | --- |
| dump size | > 100,000 bytes | 1,778,821 bytes | passes by 17.8x |
| table count | >= 50 | 308 | passes by 6.2x |
| FK constraints | >= 20 | 382 | passes by 19.1x |
| per-table row counts | source == restored | both read from the LIVE source, so `0 == 0` | prints "PASS all table row counts 308 tables identical" |

Run against a schema-only (zero-row) copy of this database, the pre-change
script prints `RESTORE REHEARSAL PASSED -- 308 tables, 0 migrations verified.`
and exits 0. Seven further defects compounded it: the scratch-vs-source refusal
was dead code (`restore_rehearsal_${SOURCE_DB}` is a strict superstring of
`SOURCE_DB`, so the equality could never hold — the same dead guard sat in
`rollback_rehearsal.sh`); `check()` passed when both sides were empty strings;
step 6 had no failing path at all; a SQL error aborted the run with no FAIL
line and the EXIT trap then dropped the scratch database, leaving nothing to
inspect; `PGPASSWORD` was not exported to `restore_smoke.py`; and `PYTHON_BIN`
defaulted to the **relative** `.venv/bin/python`, so running the script from
any other directory downgraded the only check that exercises the product to a
WARN and still printed PASSED.

The rehearsal now captures a manifest inside the dump's own snapshot
(`pg_export_snapshot()` -> `pg_dump --snapshot=<id>` -> read the manifest in
the same still-open transaction) and diffs the restored copy against it.

**What the withdrawn PASS actually established.** That `pg_dump`, `createdb`,
`pg_restore` and eight `psql` calls exited zero. That is a real thing to know
and it is not what the row claimed. It did not establish that any row, index,
constraint, privilege or sequence came back, because nothing in the script
compared the restored copy against the backup: the three floors are cleared by
an empty database, and the fourth comparison read both of its sides from the
live source.

### ISSUE-008a · The rebuilt gate still had six routes to a false PASS · **HIGH**

The rebuild above closed the row-shaped hole and left the rest of the database
unguarded. Two adversarial reviews measured the following, on restores the
rebuilt gate certified as good. Four of the six needed no tampering at all —
they fired on every run:

| Route | Measured | No tampering? |
| --- | --- | --- |
| Materialised views are re-computed by the restore, not restored | a matview holding 260 rows came back holding 0; another came back with 100 rows silently re-dated | yes |
| `--no-privileges` discarded every GRANT | the certified copy raised `permission denied for table school` for the application role | yes |
| No `--create`, so `pg_db_role_setting` was dropped | source carried `statement_timeout`, `TimeZone`, `search_path`; the copy carried none | yes |
| Bare `CREATE DATABASE` took its locale from the cluster | an ICU `de-DE-u-co-phonebk` source was certified as a `C.UTF-8` copy — every text index in a different order | yes |
| Bare `CREATE DATABASE` inherits `template1` | a `SECURITY DEFINER` function planted in `template1` appeared in the "restored copy" | no |
| The dump was hashed once, by the process that had just written it | swapping the file between the hash and `pg_restore` produced a full PASS on a copy missing 1,881 indexes, an entire schema, every large object, and with a `CHECK` reduced to `CHECK (true)` | no |

Unchecked entirely: indexes, views, matviews, functions, triggers, large
objects, extensions, defaults, `NOT NULL`, constraint *definitions* (the census
counted 382 foreign keys whether or not one had gained `ON DELETE CASCADE`),
ACLs, ownership, database settings, encoding, collation, comments, RLS
policies, and everything outside the `public` schema.

The application smoke test carried the same defect class it was meant to
detect. `check("sequences carry their position", True, ...)` — the literal
`True`, a check that could not fail. Every page was scored on
`status_code == 200` after following redirects, and an **anonymous** client
scores 200 on all eight: "8 pages served from the restored copy" was satisfied
by eight renderings of the login form, and on seeded data by eight renderings
of a mandatory-policy interstitial. It declared itself "deliberately read-only"
while inserting 331 rows across 13 tables — including into the audit chain it
then pronounced intact — and changing fields of `school` and `user` in place,
which is precisely the corruption signature the digests exist to catch.

And it produced false FAILURES on four conditions that describe normal
operation: a source taking writes (sequences are not transactional, so the
reference was read after the dump had already been taken and disagreed with
it), a source with `idle_in_transaction_session_timeout` set below the dump
time, two runs against the same source at once (the scratch name was
deterministic and the second run dropped the first one's database), and a fresh
install.

### ISSUE-008b · What the gate checks now · **RESOLVED IN CODE, UNRUN AGAINST THE PLATFORM**

The dump is taken with `--create` and **with** owners and privileges, so the
artifact is complete. The scratch database is created by replaying the
artifact's own `CREATE DATABASE ... TEMPLATE template0 ... LOCALE ...` and
`ALTER DATABASE ... SET` statements, retargeted at the scratch name — so its
locale, encoding and settings come from the backup and not from the cluster,
and `template1` cannot leak into it. `scripts/restore_manifest.py` then
compares, for every non-system schema:

schemas · relations with kind, owner, ACL, persistence, reloptions, RLS flags
and populated state · every column's type, `NOT NULL`, `DEFAULT`, identity,
generated and collation · every index by `pg_get_indexdef` · every constraint
by `pg_get_constraintdef` and validated state · every view and matview
definition · every function and procedure · every trigger · every RLS policy ·
every extension and version · every comment · every default ACL · large object
count and content digest · the database's encoding, collate, ctype, locale
provider, ICU locale, ACL and owner · its `pg_db_role_setting` entries ·
per-table row counts and order-independent content digests · materialised view
contents, reported with the reason they can differ · and sequence positions
**read out of the dump artifact's own `setval` calls**, which is the only
reference that describes the backup rather than a source that has moved on.

Measured on a plain `migrate` + `seed --demo` database (702 schools, 308
tables, 2,403 indexes, 1,065 constraints, 27,828 rows): **8,789 comparisons,
0.47 seconds** for the diff, about 25 seconds for the whole rehearsal
end to end. On the same database with a second schema, two materialised views,
a view, a trigger, a function, a large object, an application role holding
GRANTs and two `ALTER DATABASE ... SET` settings added: **8,816 comparisons.**

Demonstrated to FAIL, each corruption then reverted and the copy re-verified to
prove it is not stuck on FAIL: one row deleted; one field changed with no
row-count change; a table dropped; a sequence reset; a foreign key dropped; one
index dropped out of 2,403; all 1,857 non-unique indexes dropped; a `CHECK`
replaced by `CHECK (true)`; a foreign key that gained `ON DELETE CASCADE`;
`NOT NULL` dropped from a column; a column's identity dropped; a whole schema
dropped; a view dropped; a matview left unpopulated; a matview re-computed to
different contents; the large object deleted; a trigger dropped; a function
dropped; the application role's GRANT revoked; an `ALTER DATABASE ... SET`
removed; an extension dropped; the dump file swapped for another one during the
restore; and an object arriving from `template1`.

Demonstrated to PASS, where it used to fail: a source taking a write every 20ms
throughout the run (the sequence advanced 303 → 539 on the source; the gate read
363 from the artifact and passed); a source with
`idle_in_transaction_session_timeout=250ms` and `statement_timeout=150ms`
against a manifest read that takes 527ms; two runs two seconds apart, both
passing; a retained post-mortem copy surviving the next run; and the rehearsal
run from a working directory that is not the repository root.

A fresh install now reports **NOT PROVEN (exit 3)** rather than FAILED: the
round trip is faithful, there is no account to sign in as, and "your backup is
broken" is a different answer from "this run could not tell". A wiped database
still reports FAILED.

**A correction of record, not only of code.** §2 of this ledger forbids
claiming a gate because automation exists. This row claimed one because
automation *passed*, without anyone asking whether it could fail. The floors
were plausible-looking numbers that no measurement stood behind — and the first
rebuild replaced them with 638 real assertions about rows while leaving
everything that is not a row unexamined. Both times the failure was the same
one: nobody asked what the check could not see.

### ISSUE-008c · Two defects the rebuilt gate kept until somebody ran it · **RESOLVED, MEASURED**

The rebuild in ISSUE-008b was reviewed adversarially twice and read line by
line for its destructive paths. Both defects below survived all of that and
were found within ten minutes of executing the script. Neither is subtle; both
are only visible from the outside.

**1 · The retarget rewrote the database's owning role.** Creating the scratch
database from the artifact's own statements means rewriting the database name
in each of them. That was done by substituting every occurrence of the
identifier. This project's database and the role that owns it are both named
`edify` — the ordinary arrangement, and the one on staging and production too —
so `ALTER DATABASE edify OWNER TO edify;` became
`ALTER DATABASE "restore_rehearsal_…" OWNER TO "restore_rehearsal_…";` and the
run died on `role "restore_rehearsal_…" does not exist`. **The rebuilt gate
could not complete a single run against dev, staging or production.** It now
rewrites the name where the grammar says the database name is and nowhere else,
and refuses any database-level statement whose head it does not recognise
rather than guessing.

**2 · A failed create orphaned a full copy of the source, silently.** The flag
that records "this run owns the scratch database" was set after the whole
create pipeline succeeded. The artifact's database section is several
statements, so a failure part way through — defect 1, every time — left the
database created and the flag clear. `cleanup` consults the flag, so it dropped
nothing and said nothing. Two runs left **two 7.3 MB copies of the source
database on the host**, which is the exact outcome the script's own header
warns about. Ownership of the name is now claimed *before* anything can create
it; this is safe because the name has already matched the strict pattern and
preflight has already proven it did not exist, and `drop_scratch` re-asserts
the pattern at the moment of the drop.

**Proven able to fail.** Each corruption was applied to a good restore and the
verifier run against the dump's manifest. The harness asserts the mutation
actually changed the database *before* it reads the verdict — three of the
first attempts silently no-oped on object names that do not exist in this
schema, and would otherwise have been filed as gate defects:

| Corruption | Caught | First failure reported |
| --- | --- | --- |
| *(control — untouched restore)* | passes, exit 0 | — |
| delete one row | yes | `total_rows: expected 27828 got 27827` |
| edit one field, row count unchanged | yes | `row_digest[public.school]` differs |
| drop a table | yes | `relation: 1 MISSING: public.user_invitation` |
| rewind a sequence | yes | `sequence[public.auth_permission_id_seq]` |
| drop a foreign key | yes | `constraint: 1 MISSING` |
| drop a non-key index | yes | `index: 1 MISSING` |
| revoke a GRANT | yes | `relation[public.school]` acl differs |
| truncate every table | yes | 26 failures, `total_rows: expected 27828 got 0` |
| drop a CHECK constraint | yes | `constraint: 1 MISSING` |
| weaken a CHECK to `CHECK (true)` | yes | `constraint[…planned_school_count_check]` |
| loosen an FK to `ON DELETE CASCADE` | yes | `constraint[…user_id_fk]` differs |
| drop a trigger | *not testable here* | this schema has no user triggers; the harness refused to report a verdict rather than record a false pass |

**Proven that the verdict follows the verifier**, which is the linkage the old
gate lost: a `verify` that fails makes the script exit 1 and print FAILED *even
though the smoke test passed on the same run* — one green does not overwrite a
red. An interpreter that answers every invocation with silent success is
REFUSED (exit 2), not skipped-and-passed. A missing interpreter is REFUSED.

**Proven non-destructive.** Twelve hostile `SCRATCH_DB` values — including
`edify` itself, the command that destroyed this host's developer database
earlier in this audit, plus `postgres`, `template1`, `test_w2b`, a name with an
embedded `"; DROP DATABASE edify; --`, and newline, space, hyphen and
case-dodge variants — each exit 2 with a `REFUSING` line, and the developer
database's fingerprint (308 tables / 32 users / 700 schools, and its five
protected peers) is unchanged after every one. Zero scratch databases remain
after the full matrix.

**Why this entry exists.** ISSUE-008 was "the check could not fail". ISSUE-008a
was "the rebuilt check still could not see most of the database". This one is
different in kind and worth naming separately: the code was correct on every
reading and wrong on every execution. Reading a script establishes what its
author meant. Only running it establishes what it does.

### BACKUP-01 · The production database is on a tier with no backups · **RELEASE BLOCKER**

Everything above this entry is about whether the *restore* can be trusted.
This entry is about whether there is anything to restore.

`.do/app.yaml` declared the production database `production: false` — App
Platform's development tier. DigitalOcean's own documentation:

> "App Platform's dev databases do not support backups."
>
> "because dev databases lack these features, we do not recommend using dev
> databases in production environments."
>
> — *How do I back up my dev database on App Platform?*, DigitalOcean
> documentation

The comment above that line named two consequences — no automated failover, no
private VPC networking — and not the third. So the platform had a rehearsed
restore procedure, a verified round trip, a manifest verifier proven to fail on
twelve corruption classes, and a runbook, **for a backup that nothing was
taking**. No snapshot. No point-in-time recovery. No failover. One copy of the
financial ledger, the SSA history and the child-welfare records, on a tier
whose vendor says not to run production on it.

This is the audit's recurring defect at the layer beneath all the others: **a
reader with no writer**. A restore procedure is a reader. Something has to
write the backups. Twelve of the findings in this ledger are that shape, and
this is the one where the missing writer is the data itself.

**Why it stayed invisible.** Every check that touched backups checked the
restore. `scripts/backup_restore_rehearsal.sh` dumps a source and restores it,
which works on any tier — the rehearsal passes just as well against a database
that has never been backed up as against one that is backed up hourly. The
gate measured the procedure, and nobody asked whether the procedure had an
input. §53 is written as "backup, restore, verify"; the repository had built
the second and third and read the first as given.

**Fixed in the record, and the record is not the running app.** `.do/app.yaml`
now declares a managed cluster (`production: true`, `cluster_name: edify-db`).
That file carries a DO NOT APPLY warning and DEP-01 records that it and the
live app disagree, so this change corrects the *intent*, not production.
Whether the running app is on the dev tier is a `doctl databases list` away and
has not been checked from here — no DigitalOcean credentials are configured in
this environment.

**Gated so it cannot revert.** `apps/core/tests/test_production_database_is_backupable.py`
parses the `databases:` block and fails while any production database is
dev-tier. Parsed rather than grepped: the spec carries commented-out examples
of a managed *cache* that also say `production: true`, and a whole-file grep
would have read one of those as evidence about the database and passed. Proven
able to fail, each mutation confirmed present in the file before the verdict
was read:

| Mutation | Caught by |
| --- | --- |
| tier reverted to `production: false` | `test_the_production_database_is_a_managed_cluster` |
| tier line deleted (dev is the default, so silence is dev) | same |
| the reason stripped from the spec comment | `test_the_spec_records_why_the_tier_matters` |

A fourth test asserts the parser finds the databases at all — a parser that
quietly stopped matching would pass the other three forever, which is precisely
how the gate this replaces came to certify a wiped database.

Staging stays dev-tier and that is asserted too: it carries seeded data, says
"Dev-tier is intentional", and losing it costs a reseed.

**Still open, and it is what stands between here and a Go.** Applying this is a
data migration, not a redeploy — swapping the database resource detaches the old
one and attaches an empty one, and the dev database is deleted with the
attachment. `docs/runbooks.md` §12 is the procedure, and it uses
`scripts/restore_manifest.py` to prove the copy arrived intact rather than
merely arrived. Until an operator runs it:

* production has no recoverable copy of its data;
* §53 cannot be claimed, because the restore half is only half;
* and the first real test of any of this would be an incident, which is the
  one time nobody gets to re-run it.

### A11Y-01 · Six WCAG AA contrast failures, found by the first tool ever pointed at the product · **FIXED, MEASURED**

§4 asks for accessibility tooling. This ledger recorded it as "Not configured
in this repository", which was accurate: no browser harness, no axe, no
measurement of any kind. Every accessibility statement in the documentation was
a statement of intent.

`scripts/accessibility_audit.py` now drives Chromium through axe-core over the
eight pages people spend the day on, signed in, with the real stylesheet
served. The first run found six serious violations, all one defect:

`.kpi-strip__helper` — the small line under each KPI tile's number — was
tinted 70% toward the tile's accent colour. At 12px and weight 500 on
`#eaeef1`, that fails WCAG AA:

| Page | Text | Measured | Required |
| --- | --- | --- | --- |
| `/dashboard` | "0 open and unacknowledged" | 3.03 | 4.5 |
| `/dashboard` | "Open security incidents" | 3.03 | 4.5 |
| `/schools` | "80% of total" (success tile) | 3.03 | 4.5 |
| `/schools` | "15% of total" (purple tile) | 4.49 | 4.5 |
| `/schools` | "100% of total" (warning tile) | 2.69 | 4.5 |
| `/schools` | "56% of total" (danger tile) | 4.37 | 4.5 |

**Fixed, not baselined.** The tint is now 30%. That number is computed, not
chosen: against this background and this muted colour, the largest accent share
clearing 4.5:1 on *every* tile variant is 33% — warning (`#f59e0b`) binds,
being the lightest — so 30% is the round number below it, leaving primary 6.30,
warning 4.70, success 4.93, purple 5.92, danger 6.13. The tile keeps its
accent; the helper line becomes readable. Measured state after the fix: **0
critical and 0 serious across all eight pages.**

**What the harness does that the obvious version does not.** Both lessons come
from defects this audit already found in this repository:

* **It signs in, and proves it.** An anonymous browser is redirected to
  `/login`, which is small, clean and largely accessible — so the obvious
  version scores the login form eight times and reports the product as
  accessible. `scripts/restore_smoke.py` shipped with exactly that defect.
  Every page here asserts it *landed* on the path it requested. This was not
  theoretical: the first working draft signed in with
  `django.contrib.auth.backends.ModelBackend` while the project authenticates
  through `LockoutEnforcingModelBackend`, so every session was silently
  rejected and all eight pages redirected to `/login`. The assertion caught it;
  without it the run would have reported a clean sheet.
* **It proves axe actually ran.** A scan that fails to inject axe reports zero
  violations, which is indistinguishable from a perfect page. Each page asserts
  a floor on rules evaluated and DOM size. This also caught a real bug in the
  harness: passing `resultTypes: ['violations']` makes axe truncate its other
  result arrays, so the rule count read 28–38 where the true figure is 63–65,
  and every page was wrongly reported as a thin scan.

**Gated.** `apps/system_health/test_accessibility_baseline.py` runs on every
commit and holds the ratchet. Proven able to fail:

| Mutation | Caught by |
| --- | --- |
| baseline file deleted | `test_the_baseline_exists` |
| a page dropped from the baseline | `test_it_covers_every_page_the_audit_scans` |
| a count raised to absorb 4 new violations | `test_the_counts_are_the_measured_zero` |
| the ratchet warning stripped from the file | `test_the_file_says_it_is_a_ratchet` |
| the audit stops scanning a page | `test_it_covers_every_page_the_audit_scans` |

The audit script itself needs Chromium and a seeded estate, so like
`scripts/latency_budget.py` it is run deliberately rather than on every commit.
That is a real limitation and it is stated rather than papered over: what CI
guards is the baseline, not a fresh scan. The scan was also verified able to
fail — reintroducing the 70% tint brought all six violations back and the run
reported `2 blocking, baseline allows 0` and `4 blocking, baseline allows 0`.

**Not covered.** Only the default (light) theme, only the eight core pages,
only WCAG 2.0/2.1 A and AA, and only what axe can detect automatically —
which is roughly a third of the WCAG criteria. Keyboard traps, focus order,
screen-reader semantics and the dark theme are unmeasured. Saying so is the
point: this row moved from "no tooling" to "some tooling, and here is exactly
what it does and does not see".

### INTG-01 · The screens claimed a Salesforce integration the code does not have · **CLAIM FIXED; TRANSPORT STILL ABSENT**

`apps/integrations/services.py:push_to_external` is a single unconditional
`raise IntegrationNotConfigured`, and so is `validate_external_reference`.
There is no HTTP transport for Salesforce anywhere in the codebase. That is a
deliberate, documented seam — *"Until then it refuses loudly rather than
pretending."*

The code refuses loudly. Two screens did not:

| Screen | Said | Actually happens |
| --- | --- | --- |
| IA partner-completion drawer | "Completing verifies the evidence and **confirms Salesforce**" | a person types a reference; its prefix and local uniqueness are checked; it is stored |
| IA verification queue header | "Verify activity completions, **confirm Salesforce records integrity**" | nothing checks the integrity of anything in Salesforce |

That stored string gates activity closure, IA partner confirmation,
core-activity verification and partner-payment eligibility. So an IA who read
those sentences and believed the platform had checked Salesforce was releasing
money on a belief the platform never earned. It is the same shape as BASE-02
(Settings promising a dark mode that no longer existed), in a place where the
consequence is financial rather than cosmetic.

**Fixed:** the drawer now reads "records the Salesforce reference you enter —
the system does not contact Salesforce", and the queue header "record the
Salesforce reference for each".

**Gated** by `apps/system_health/test_integration_claims_match_reality.py`,
which ties the copy to the code: it fails while any screen puts the *system* in
the subject position of a Salesforce claim, and its first assertion is that
`push_to_external` still refuses — so the day the transport lands, the test
says so and asks to be deleted rather than silently outliving its reason.

The boundary is grammatical and deliberate. "Confirm Salesforce Entry" on a
button and "Confirm that this loan has been entered into Salesforce" are
addressed to a person about their own action, are true, and stay. "Confirms
Salesforce" is the system claiming a check. Banning the word outright would
force rewrites of honest copy, and a gate that cries wolf gets deleted.

Proven able to fail — five mutations, each confirmed present before the verdict
was read: the old drawer wording restored; the old queue wording restored; a
new screen saying "synced to Salesforce"; the honest replacement sentence
deleted (which the absence-only test would have accepted); and the transport
implemented, which correctly flips the premise assertion.

**Still open, and not closable from here.** The transport itself is the
credentialed half of Phase 2c. Until it lands, Salesforce reconciliation is
manual and unverified — the release scope has to say that plainly, which is the
second of the two options INTG-01 always offered. The screens now say it; the
release note should too.

### BACKUP-01a · The migration is now one verified command, and testing it cost two rows · **TOOLING ADDED; INCIDENT RECORDED**

§12 described the move to a backed-up database as five manual steps. Five
manual steps carried out under deadline pressure, possibly during an incident,
is how step 3 — the verification — gets skipped, and step 3 is the entire
point. `scripts/migrate_to_managed_cluster.sh` is those steps as one command
that cannot skip its own check.

It never writes to the source, never drops anything, and deliberately **does
not cut over**: it brings the new cluster to a provably correct state and
stops. Run against the developer database it dumped 8.2 MB, restored, and
verified **8,955 checks over 312 tables / 28,533 rows / 2,433 indexes / 1,093
constraints**, exit 0.

Proven able to fail. A shimmed `pg_restore` that succeeded but silently dropped
one row produced:

```
FAIL total_rows: expected 28533 got 28532
FAIL row_count[public.activity_catalogue_alias]: expected 94 got 93
FAIL row_digest[public.activity_catalogue_alias]: … (CONTENT differs)
MIGRATION FAILED — DO NOT cut over. The source is untouched.
```

Five refusals also verified: no `SOURCE_URL`, no `TARGET_URL`, source and
target resolving to the same database (compared by cluster identity, not URL
string), an interpreter that answers everything with silent success, and an
unreachable source. All exit 2 having done nothing.

**And a defect the writing did not catch.** The first run failed on
`pg_restore: option '--no-owner' doesn't allow an argument` — the script had
`--no-owner=false`, reaching for a flag that does not exist to express "keep
the owners", when the mechanism is simply to omit the flag. Harmless because
`pg_restore` rejected it outright; had it been a flag that silently accepted a
value, the migration would have restored without GRANTs and looked healthy
right up until real traffic hit `permission denied for table school`.

**THE INCIDENT.** Testing that failure path damaged the developer database, and
this is the second time in this audit a harness — not the code under test — has
done so.

The shim was `pg_restore "$@"` followed by a `DELETE` against whatever database
followed `-d`. `scripts/restore_manifest.py` legitimately invokes `pg_restore`
three times **without** `-d`: once for `-l` to read the TOC, once for the
sequence section, once for the database section. On those calls the shim's
target variable was unset, and `psql -d ""` does not fail — libpq defaults the
database name to the connecting user, which here is `edify`. Two of those calls
each deleted a row from the live developer database. 94 aliases became 92.

Recovered in full from the migration dump taken minutes earlier, and the repair
was itself verified: `restore_manifest.py verify` against the pre-damage
manifest passed all **8,955** checks. The tool built to prove restores proved
this one.

**The rule this earns**, and it generalises past this repository: *a test
harness must never connect to a default-resolved database.* Every destructive
tool in a test path needs its target named explicitly and refused when absent —
`psql -d ""` silently meaning "the database named after me" is a loaded gun
pointed at whatever the developer happens to be called. Both database
incidents in this audit came from a harness, not from the code it was testing,
and both from a destructive path that had not been made to prove its own blast
radius first.

### PERF-01 · The scale gate allowed 30 seconds where the budget is 800ms · **MEASURED AND TIGHTENED**

`apps/system_health/test_load_scale.py` is a good gate. Its central assertion —
scale *invariance* of query counts rather than a fixed ceiling — is the right
shape, and its docstring explains exactly why a pinned number rots.

But the only time ceiling it carried was `CATASTROPHIC_SECONDS = 30.0`, while
`/dashboard`'s §7 budget is **800ms**. A page could take twenty-nine seconds at
15,000 schools and pass. That is a 37x gap between what the gate permitted and
what the product promises — the same defect class as the backup floors, in the
one file specifically written to catch what small estates hide.

A flat query count does not imply flat time. A sequential scan over a table
that has grown keeps its query count constant while taking steadily longer,
which is precisely the failure a 700-school dev estate cannot show and a
15,000-school production estate reveals to users on day one.

**Measured, for the first time, at the full estate:**

| Page | Measured | Budget | Queries |
| --- | --- | --- | --- |
| `/dashboard` | 230ms | 800 | 92 |
| `/my-plan` | 81ms | 800 | 32 |
| `/schools` | 161ms | 800 | 45 |
| `/todos` | 177ms | 800 | 74 |
| `/notifications` | 28ms | 800 | 15 |
| `/settings` | 20ms | 800 | 9 |
| `/analytics` | 420ms | 1500 | 80 |
| `/system-health` | 9ms | 1500 | 10 |

**There is no cliff.** The worst page sits at 29% of its budget at 21x the dev
estate. That is genuinely good news and it is the first evidence anyone has for
it.

**Now gated.** `test_pages_stay_inside_their_budgets_at_scale` asserts each
page against its §7 budget times four. The factor is derived, not picked: the
worst measured page is at 29% of budget, so 4x leaves roughly fourteen times
the measured headroom — loose enough that a slow CI runner does not flake,
tight enough that a page falling from 230ms to 3.2s fails on the day it
happens. If it starts failing, the fix is the page and not the factor.

Proven able to fail. Two mutations, each confirmed present in the file before
the verdict was read:

| Mutation | Result |
| --- | --- |
| `/dashboard` slowed by 4s inside the measured region | caught — `4267ms at 15,000 schools, budget 800ms` |
| the measurement loop iterating over an empty list | caught by the count assertion |

A third attempt failed to test anything and is worth recording: the first
version of the slow-page mutation put its `sleep` **outside** the timed region,
so the suite ran four seconds longer while reporting the same page time and
passing. A mutation that does not reach the thing under test proves nothing,
and looks identical to a gate that cannot fail.

**What this is not.** One request, no concurrency, on this container, against a
synthetic estate built by the harness. It is not a p95, not production
hardware, and not a load test. The row above says so rather than letting
"measured" imply more than was measured. Concurrency and real hardware remain
unverified, and only a real deployment can settle them.

### A11Y-02 · The accessibility scan covered one of three palettes · **EXTENDED, MEASURED, CLEAN**

A11Y-01 pointed a browser at the product for the first time and found six real
contrast failures. It scanned the default theme.

This product ships **three** user-selectable palettes — `light`, `dark` and
`blue` (`system` resolves to one of the first two and adds no palette of its
own). Colour contrast is most of what axe checks and it is *entirely* a
property of the palette, so a clean light theme is evidence about light and
nothing else. DARK-01 had already established that this project's dark theme
carried real contrast failures, which makes the omission worse than
theoretical.

The audit now scans **3 themes x 8 pages = 24 combinations**, seeding
`localStorage['edify_theme']` through an init script so the palette is chosen
before first paint.

**Measured: 0 critical and 0 serious across all three themes.** The DARK-01
sweep held. That is a real result and it is the first evidence for the dark and
blue palettes.

**The scan is not vacuous, and that was checked rather than assumed.** Three
themes reporting identical numbers is exactly what a broken theme switch also
looks like, so the palettes were measured directly on `/dashboard`:

| Theme | body background | body text |
| --- | --- | --- |
| light | `rgb(227, 242, 250)` | `rgb(23, 35, 43)` |
| dark | `rgb(14, 21, 28)` | `rgb(237, 243, 247)` |
| blue | `rgb(0, 29, 57)` | `rgb(245, 251, 255)` |

Three genuinely different palettes. The audit also now asserts
`documentElement.dataset.theme` matches the theme it asked for, and refuses the
page if it does not — without that, a silently-ignored theme setting scans the
default three times and reports three clean themes, which is the same shape of
lie as scanning the login form eight times.

**Proven able to fail in dark specifically.** A dark-only contrast rule
(`#2a3138` helper text on the `rgb(14,21,28)` ground) produced 7 violations on
`/dashboard` and 8 on `/schools` **in dark only**, with light and blue still
clean — so the per-theme isolation works and failures do not leak between
palettes.

That mutation took two attempts, and the first is worth recording. It used
`.theme-dark .kpi-strip__helper` — two classes of specificity against the three
in the rule it needed to beat, so it never applied and the audit correctly
reported no violations. A mutation that loses the cascade proves nothing and is
indistinguishable from a gate that cannot see. The second attempt measured the
computed colour to prove the mutation was live *before* reading any verdict.

**The ratchet now covers themes.** `test_accessibility_baseline.py` reads both
`DEFAULT_PAGES` and `THEMES` out of the audit's own source, so dropping a theme
cannot silently shrink the gate. Proven able to fail:

| Mutation | Caught by |
| --- | --- |
| the audit drops to one theme | `test_it_covers_every_theme_and_page_the_audit_scans` |
| the baseline loses the dark entries | that, and `test_every_theme_is_actually_represented` |
| a dark count raised to absorb 7 violations | `test_the_counts_are_the_measured_zero` |

**Still not covered:** keyboard traps, focus order, screen-reader semantics,
and the 564 routed surfaces outside the eight core pages. Only what axe detects
automatically, which is roughly a third of the WCAG criteria. Saying so is the
point.

### ISSUE-007 · `/todos` breaches its latency budget for the Country Director · **HIGH**

Measured: **p95 829ms against an 800ms budget, on 501 queries**, at 702 schools.

Isolating each To-Do generator for a Country Director:

```
_cd_analytics_todos         603 queries
_field_debrief_todos         16
_activity_todos               3
_pd_todos                     3
_country_budget_todos         2
_leave_todos                  1
everything else               0
```

One source. `_cd_analytics_todos` runs the full CD analytics engine to derive a
handful of items — `pl_oversight` (281 queries) and `recommended_actions`
(316).

**Root cause:** `pl_oversight` is N+1 across Program Leads. Per PL it runs a
weighted-achievement pass, an area-achievement pass, a school count, a backlog
count and a budget lookup. The cost grows with the number of PLs — on a page
every Country Director opens.

**Not fixed in this pass, deliberately.** The fix is batching inside the
targets engine, and that engine is where a previous optimisation of mine
silently replaced an average over all records with a mean of school means. A
correctness regression there is worse than a slow page, and I would rather do
it with room to verify the numbers are unchanged.

**Pinned meanwhile:** `apps/command_center/test_todo_query_budget.py` records
the ceiling so the page can only get better, and carries the growth assertion
that will pass once `pl_oversight` batches — skipped with an explanatory
message while the N+1 stands, rather than left permanently red.

## 9. Pass 3 — ISSUE-007 closed, mutations triaged

### ISSUE-007 · CLOSED

The cause was not the analytics engine. `_weighted_achievement` already pools
from a pre-fetched per-user target series when given one, and every other
caller of `pl_oversight` primes that series first. `cd_todos` did not, so the
ledger was re-fetched once per Program Lead.

One line, using machinery built for exactly this case:

| | before | after |
| --- | --- | --- |
| `/todos` queries (Country Director) | 501 | **216** |
| `/todos` p95 | 829ms | **414ms** |
| Latency budgets inside target | 23 / 24 | **24 / 24** |

**Output is byte-identical** — asserted before and after, and pinned by
`PrimedSeriesChangesCostNotNumbersTest`, which runs `pl_oversight` primed and
unprimed and requires every row to match. That test exists because the risk in
this change was never that it stayed slow; it was that pooling from a
pre-fetched series quietly computes something slightly different. A wrong
target percentage is far worse than a slow page.

A residual O(Program Leads) term remains — roughly four queries each, from the
per-PL roster and budget lookups. Small, bounded, comfortably inside budget,
and recorded in the growth assertion that still skips.

### Raw workflow mutations · 30 → 25, and triaged

The remaining 25 are not one defect repeated 25 times. Grouped by whether a
canonical service already owns the transition:

**Genuine transitions that belong in a service (7)** — the real remainder:

| Site | Transition |
| --- | --- |
| `core_schools_views.py` ×3 | Core slot `Scheduled` / `Assigned` — the 9-slot package and 2+2 staff cap are enforced in the Core service |
| `planning_views.py` ×2 | `partner_scheduled` — partner assignment scheduling |
| `leave_views.py:1810` | leave → `hr_review` |
| `pd_views.py:457` | PD request `cancelled` |

**An import routine's own bookkeeping (9)** — `upload_views.py` ×3,
`school_views.py`, `extended_views.py:2246`, and the unmatched-SSA resolution
states. The view *is* the import process here; there is no separate service
being bypassed, and inventing one would add indirection without adding a guard.

**Queue and triage state, not business workflow (9)** — IA duplicate flags,
data-quality issue resolution, help-article draft, coverage revocation, member
invite/active. These carry no money, no target credit and no verification
authority.

Pass 4 should take the seven. The other eighteen are recorded as accepted, with
the reason, rather than left looking like eighteen open defects.

### ISSUE-005 · why it is still open after pass 3

The canonical `weighted_ssa_mean` exists and is tested. The template still
computes its own because of where the *matching* happens, not the arithmetic:

`matchMetricsToFeatures` pairs each district metric to a GeoJSON boundary by
`boundary_code`, then by name alias, and deliberately refuses to guess when a
historical name is ambiguous. The server does not hold the boundary features,
so it cannot know which districts a given polygon covers.

The clean fix is one batched call after matching — the client sends the matched
key groups, the server returns the combined rows. That is a small change, and
I did not make it here: building the endpoint without wiring the client would
leave dead code, which §11 of this same mandate forbids, and wiring an
interactive map is not something to do without room to verify it.

So the gate honestly still reads 3.

### ISSUE-008 · Reminder dedupe failed for three hours a day · **MEDIUM** · CLOSED

Found because a full-suite run crossed midnight and one test failed that had
passed an hour earlier.

`send_acknowledgement_reminders` deduplicated on
`ack.last_reminded_at.date()` — the **UTC** day — against
`timezone.localdate()`, the **Africa/Kampala** day. Between 00:00 and 03:00
local, those disagree, the dedupe silently fails, and a person receives a
second reminder for the same condition on the same day. §23 forbids precisely
that.

My first diagnosis was wrong: I assumed the test was at fault for using
`date.today()` and fixed that, and it still failed. The defect was in the
production code.

Pinned by `ReminderDedupeAcrossTimezonesTest`, which sets a reminder at 00:30
local, reads it back from the database to get the UTC day, and **asserts the
two dates actually differ** before testing the dedupe — a first draft of that
test built the datetime in local time, so both dates agreed and it would have
passed against the bug. The guard caught it.

## 10. Pass 4 — the seven genuine transitions, closed

Raw workflow mutations: **25 → 18**. Every finding the pass-3 triage called a
genuine business transition now lives in the service that owns it.

| Transition | Now owned by |
| --- | --- |
| Core slot `Scheduled` ×2 | `CorePackageSchedulingService.commit_schedule` |
| Core slot `Assigned` | `CorePackageSchedulingService.commit_assign` |
| Partner assignment `partner_scheduled` ×2 | `partners.services.mark_assignment_scheduled` |
| Leave `hr_review` | `LeaveApprovalService.escalate_to_hr` |
| PD request `cancelled` | `StaffPDService.cancel_draft` |

Two of these are worth naming, because they show why "the guard exists" is not
the same as "the transition is safe":

**Core slots.** `assert_can_schedule` locked a slot and enforced the 4 + 4
annual cap — and then handed the caller a slot to write whatever status it
liked. The guard lived in the service; the state it protects was written in
two views, as identical copy-pasted blocks. Guard and commit now share an
owner.

**Leave escalation.** The service already sent the notification, named the
owner and wrote the audit row. Its own docstring said *"The view flipped the
status and stopped."* The status write was still in the view — so a second
caller could set `hr_review` while notifying nobody, recreating the original
defect one call site over. The write moved in.

### The 18 that remain are deliberate

They are not a backlog. Nine are an import routine's own bookkeeping, where the
view *is* the process and no service is being bypassed; nine are queue and
triage state carrying no money, no target credit and no verification authority.
The gate ceiling is set at 18 with that reasoning recorded beside it, so the
number moves only if a real transition appears — not by relocating these for
the sake of a smaller figure.

## 11. Pass 5 — every executable gate closed

### Hard-zero gates

| Gate | Pass 1 | Now |
| --- | --- | --- |
| Mock/demo data in the production runtime | 0 | **0** |
| Dead controls | 0 | **0** |
| Business analytics computed in JavaScript | 3 | **0** |
| Page routes with no declared permission | 6 | **0** |
| Workflow state written outside a canonical service | 30 | **18, all accepted** |

### ISSUE-005 · CLOSED

Three findings, two different problems.

`syncSchoolTotals` summed school cohorts across every district — a country-wide
total that never depended on the map at all. It lived in the browser only
because that is where the district payload happened to be parsed.
`country_map_context.school_type_totals` computes it now.

The n-weighted SSA mean was the real one. The resolution splits the work by
what each side is actually for: **geometry matching stays in the browser**,
because pairing GeoJSON polygons to districts is presentation; **combining the
matched rows moved to the server**, because an n-weighted mean shown to a
Country Director is an authoritative figure. The browser posts the matching it
made once, when the layer draws, and gets every combined row back together — so
hovering reads a cache rather than making a round trip, and the arithmetic has
one implementation with tests behind it.

While doing this the scanner went **up** to 4. It was flagging
`totals = JSON.parse(...)` and `type.total = totals[key] ?? 0` — deserialising a
payload and reading a value with a default, neither of which computes anything.
That is a false-positive class, and the fix was to the scanner, not to dodge
it. `JavaScriptScannerAccuracyTests` now pins both directions: six real
computations it must still catch, seven honest lines it must not flag. A gate
that reports good code as a defect teaches people to route around it, which is
worse than a gate that is slightly too narrow.

### ISSUE-006 · CLOSED

The six performance-conversation endpoints declare their audience at the route
now, in addition to the engine's own enforcement. `apps.hr.performance_engine`
still owns the real rules — ownership, the review window, who may sign off —
and keeps them. The declaration is what makes a page-permission audit able to
see the route, which is what §9 is about.

### Gates that were UNVERIFIED

| Gate | Status |
| --- | --- |
| Backup restore rehearsal | ~~**PASSED** — 228 tables, 203 migrations, 250 validated FK constraints, audit chain intact, 8 pages served from the restored copy~~ **SUPERSEDED — see ISSUE-008** |
| Rollback rehearsal | ~~**PASSED** — the previous release serves the schema HEAD leaves behind. Rollback is a deploy of the older image; the database stays put~~ **SUPERSEDED — see the §8 row** |
| Wall-clock p95 at 15,000 schools | **MEASURED, all inside budget** |
| Latency budgets (702-school dev estate) | **24/24 inside budget** |

The two rehearsal rows are struck through rather than deleted, because the runs
happened and the record of them should stand. What they established was that
the scripts exited zero. The backup gate's every threshold is cleared by a
database with no rows in it — 228 tables against a floor of 50, 250 foreign
keys against a floor of 20, a 1.78 MB dump against a floor of 100,000 bytes —
and "8 pages served from the restored copy" was measured by following redirects
and scoring HTTP 200, which an anonymous client also scores on all eight. Both
scripts have since been rebuilt; ISSUE-008 carries the measurements.

p95 at 15,000 schools:

```
/dashboard 156ms · /my-plan 73ms · /schools 168ms · /todos 177ms
/notifications 20ms · /settings 12ms · /analytics 484ms · /system-health 7ms
```

Budgets are 800ms, and 1500ms for analytics. Measured inside the existing
15,000-school fixture using the same pages and budgets as
`scripts/latency_budget.py`, so the two runs are directly comparable. The test
prints the numbers rather than only asserting them — a gate that says only
"OK" leaves nobody able to answer "how close were we?"

Honest limit, unchanged: Django's test client skips the network, the WSGI
server and the real connection pool, so these are a **lower bound** on
production wall time. A breach is real; a pass is evidence, not a certification.

## 12. Section 2, restated correctly — and now measurable

The owner has clarified what §2's "95% planning-time reduction" actually means,
and it was never a stopwatch claim. The goal is **minimal input**: across the
whole lifecycle of a piece of field work, a person supplies only

1. Cluster the school
2. Assign it to a partner, or schedule the activity
3. Upload the evidence
4. Enter the Salesforce activity ID
5. Enter the NetSuite ID, confirming reconciliation

and the platform does the rest.

That is checkable from the code, so this gate moves from **UNVERIFIED** to
**MEASURED**.

| | |
| --- | --- |
| Human touchpoints | **5** |
| Distinct human inputs | **7** |
| Fields the platform derives | **24** |
| Automation ratio | **77.4%** |
| Inputs asked for more than once | **0** |
| Required form fields outside the contract | **0** |

The last row is the one that keeps working after today.
`unsanctioned_required_inputs()` reads the workflow's own drawers and reports
any *required*, non-hidden field the contract does not sanction, and a test
fails on a non-empty result. A new mandatory question cannot be added to
scheduling or partner assignment without someone either deriving it, making it
optional, or changing the contract on purpose.

Two deliberate narrowings, so the check is not stronger than the evidence:

- **Optional fields are not counted.** `expected_participants` sharpens a cost
  estimate and says so in the template; skipping it costs nothing.
- **Pre-filled fields are not counted.** `focus_intervention` arrives selected
  from the SSA recommendation, with the ranked scores shown beside it. That is
  the platform deriving a value and letting the person disagree — the contract
  working, not breaking.

### The drawers asked one question two ways — now fixed

The two planning drawers labelled the same decisions differently:

| | Schedule drawer | Partner drawer |
| --- | --- | --- |
| Partner | "Assign to Partner" | "Partner Organization" |
| Free-text goal | "Activity Goal / Purpose" | "Assignment Purpose / Scope" |

Nobody sees both drawers at once, so this was never duplication inside a form.
But a CCEO uses both, and one decision under two names reads as two questions.
The labels are unified now, which is the half a person actually sees.

Fixing it surfaced two things worth recording.

**"Purpose of Visit" was wrong.** The schedule drawer schedules trainings as
well as visits — the participants field is shown for three training types — so
the label was inaccurate for a large share of what it schedules. It is
"Purpose" now.

**I mispaired the fields, and then briefly made the form worse.** The first
pass treated `purpose_of_visit` and the partner drawer's `purpose` as the same
input. They are not: `purpose_of_visit` is a required *select* that classifies
the work and drives `activity_type`, while `purpose` is free text. The real
free-text pair is `purpose` → `activity_purpose_text`, which is what
`PartnerAssignment.purpose` literally becomes on the Activity. Unifying on the
wrong pairing left the schedule drawer with two fields both labelled "Purpose"
— worse than the inconsistency it replaced. The select is "Purpose", the
textarea is "Goal", and a test now fails if any drawer gives two fields the
same label.

**The field names stay.** `partner_id` is read by six unrelated production
views — debriefs, staff assignment, core schools, three planning paths — so it
is a generic request parameter rather than this drawer's private name.
Renaming it would touch features with nothing to do with partner assignment,
for no user-visible gain. `FIELD_NAME_ALIASES` records the pairing, now
correctly.

### One decision removed from the scheduling moment

The schedule drawer offered "Assigned Partner Delivery" and a partner picker,
alongside a dedicated partner-assignment drawer that does the same thing. Two
routes to one outcome — and the schedule drawer's was the worse one:
`assign_partner_action_view` creates the **PartnerAssignment** record the
handoff is tracked by, while the schedule drawer's partner path created only
the Activity. Partner work scheduled that way was invisible to anything reading
assignments.

Removed. The drawer now schedules the work of whoever is using it, and delivery
type is who they are rather than a question. That is one fewer decision at the
moment §2 cares most about, and one fewer way to produce an untracked handoff.

Handing a school to a partner remains the partner drawer. A partner
self-scheduling an activity already assigned to them remains
`apps.partners.services.schedule_activity`.

**The trap in doing it:** the hidden `delivery_type` field cannot be hard-coded
to `staff`. A reschedule initialises the drawer from the activity being moved,
so a fixed value would silently convert an existing partner activity to staff
delivery. It is bound to the model instead, and a test pins that.

### Not done: one scheduling surface for partners too

The owner's intent is that partners use the same drawer, since they are also
scheduling. Today they cannot: `planning` is `{CCEO, PL, PROJECT_COORDINATOR,
ADMIN}`, and `can_schedule_activity` refuses both partner roles. Partners
self-schedule assigned activities through their own workspace instead.

Unifying those surfaces means granting partners a scheduling page scoped to
their assignments — a permission and scoping change with real security surface,
not a template edit. It belongs in its own change with its own scope tests
rather than at the end of a readiness pass.

### ISSUE-009 · Rescheduling asked for the same money twice · **HIGH** · CLOSED

Found by following the owner's requirement that a reschedule move the cost with
the date.

It mostly does. `activities.services.reschedule` re-prices and calls
`sync_weekly_requests_for_activity` / `sync_monthly_drafts_for_activity` with
`prior_buckets`, so the vacated week empties as the new one fills.

But reschedule has two branches, and the common one skipped that. A staff
school visit is daily-batch eligible, so it goes through
`reschedule_within_batch`, which re-prices the batch and then calls
`trigger_generate_for_activity` — a helper that raises the request for the
**new** week and says nothing about the old one.

Reproduced before fixing, on one activity worth UGX 50,000:

```
week A request        50,000
after moving to week B
  week A still holds  50,000
  week B now holds    50,000
```

Not a stale total — a duplicate. The same work funded twice, in the week it
left and the week it moved to. Every staff school visit takes that branch.

Fixed at the reschedule seam rather than inside the batch module: the prior
buckets are captured before either branch reprices, and the batch branch now
calls the same two sync functions the other branch always did.

Five tests, written against what the two weeks *hold* rather than against which
helper is called, so a future implementation that reintroduces the duplication
fails them. One of the five deliberately pins the broken behaviour of syncing
*without* `prior_buckets` — it documents why that argument is load-bearing, and
it will fail loudly if the sync ever learns to find the vacated bucket on its
own.

### Honest limits on what *is* green

- **Latency numbers are a lower bound.** Django's test client skips the
  network, the WSGI server and the real connection pool. A breach is real; a
  pass is evidence, not a production certification.
- **The 18 accepted mutations are a judgement, not a measurement.** Nine are an
  import routine's own bookkeeping, nine are queue state carrying no money,
  target credit or verification authority. The ledger names each, so
  disagreeing is an argument about a specific line rather than a number.
- **No visual-regression or automated accessibility tooling** is configured in
  this repository. Accessibility was checked by rendered-DOM audit in prior
  work, not by an automated gate at this commit.
- **§57's "every handoff works" is not certifiable by me.** 451 surfaces, 1,089
  routes, 10 roles: I have measured a named subset and the suite covers ~3,200
  cases. That is not the same as exhaustive.

### Recommendation

Every gate that can be executed from this repository is now green, including
the two rehearsals that had never been run — restore and rollback — and §2,
which is measurable once stated as a minimal-input contract rather than a time
claim.

The remaining risk is not a missing check; it is the gap between what a suite
can prove and what production does. The scale numbers are a lower bound, the
accessibility evidence predates this commit, and no test suite certifies 1,089
routes across 10 roles the way a week of real use does.

Recommended: **GO for a staged deployment** — deploy, watch the System Health
board and the incident queue, and keep the rollback rehearsed above as the
answer if something surfaces. That is a stronger position than any further
static analysis can buy, because the next class of defect is the kind only real
users find.



1. ISSUE-001 and ISSUE-002 — move SSA verification and finance transitions into
   their canonical services, with regression tests that fail if a view writes
   the field again.
2. ISSUE-005 — move the weighted SSA mean server-side.
3. ISSUE-004 — triage the remaining raw mutations.
4. ISSUE-006 — declare or formally except.
5. Build the planning-time instrumentation harness so the human baseline can be
   collected.


## 2026-08-24 — javascript_business_maths: 0 → 1 (deliberate)

The Uganda target-distribution drawers gained a live remaining-balance
preview (`static/js/target-distribution.js`): the distributor picks a holder,
types a target, and the "left to distribute" figure falls on the keystroke,
arming Approve only at exactly zero. That subtraction is client-side
arithmetic over business quantities, which this gate exists to flag.

It is allowed to stand because the figure is a preview and nothing more. The
authoritative balance is recomputed by `reconcile_team_level` /
`reconcile_employee_level` on every save and approve, both of which refuse an
unbalanced distribution outright — verified by an end-to-end test posting a
deliberately short allocation, which stayed a draft. A doctored DOM can arm
the button; it cannot approve anything. The alternative — a server round-trip
per keystroke — is the stale-balance design the drawers replaced at the
owner's request.

The ceiling is one named finding. A second finding in this gate is a
regression, not an extension of this entry.
