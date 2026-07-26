# Reliability and Security Audit — 2026-07-26

Audit commit: `4e353629` (baseline) → work on `audit/reliability-2026-07-26`
Branch: `main` @ `2ee1af88` + audit branch
Environment: local (Python 3.13.12, Django 5.2.16, PostgreSQL 16.13, Node 24.14.0, Darwin arm64)

This is an interim report against a very large brief. It is written to be
honest about the boundary: what was executed and closed with evidence, and what
was not executed at all. Nothing below is marked closed on the strength of
reading the code.

---

## Baseline (section 5)

| Gate | Result |
|---|---|
| `manage.py check` | 0 issues |
| `check --deploy` under production settings | 0 security warnings |
| `makemigrations --check` | no drift |
| `migrate --plan` | no pending operations |
| `compileall` | exit 0 |
| `ruff check` | pass |
| `ruff format --check` | **4 files drifted → fixed** |
| `pytest` (full) | 2030 passed, 0 failed |
| `bandit` | 0 High, 0 Medium, 398 Low |
| `pip-audit` | no known vulnerabilities |
| `npm audit` | 0 vulnerabilities |
| `npm run build:css` | **bundle 1 utility stale → fixed** |
| `collectstatic` | 199 files |
| CodeQL @ `4e353629` | success |
| CI @ `4e353629` | **failed on ruff format → fixed in `2ee1af88`** |

Note on `check --deploy`: the production settings module *refuses to load*
without `ENABLE_DEV_SEED=false` and `AUTHZ_MODE=enforce`. That is the
environment-safety gate working, and it is worth knowing it fires before
anything else does.

---

## Findings

### R-01 — Invitation email sent while holding a row lock  ·  HIGH  ·  CLOSED

**Where** `apps/hr/recruitment_service.py::hire` → `apps/admin_users/services.py::create`

`hire()` is `@transaction.atomic` and takes `select_for_update()` on the
Application row — correctly, since that is what stops two recruiters
provisioning the same candidate. It then calls the canonical user-creation
service, which sent the invitation email before returning.

So the lock on the Application row, and a connection from the pool, were held
for the length of a call to an email provider — up to the mailer's 15-second
timeout. A provider having a slow afternoon becomes lock contention, then pool
exhaustion, then an outage in a system with nothing wrong with it.

**Why review would not catch it** The send sits several frames below the
`atomic`, and the `atomic` is a decorator on a function in a different app. A
lexical scan for `mailer.send` inside an `atomic` body finds nothing — I ran
one first, and it returned zero.

**Repair** `apps/core/blocking_io_guard.py`. Two parts:

- `refuse_inside_transaction()` is called at the point of I/O by both
  `MailerService.send` and `SmsService.send`. It asks the *connection* whether
  a transaction is open, so it sees the condition however deep the caller is.
  Raises under test; logs and proceeds in production, because by then the send
  is already committed to and refusing it would turn a latency problem into a
  person never receiving their sign-in code.
- `send_after_commit()` defers the send past commit when — and only when — the
  application has a transaction open. Also the more correct order: an
  invitation for an account whose creation then rolled back is a link that
  cannot work, sent to someone with no way to know why.

`inviteToken` in the response previously read the delivery result, which is no
longer known when the response is built. It now reads `mailer.is_configured`,
which answers the same question ("does this admin need to pass the link on by
hand?") and answers it deterministically.

**Evidence** Full-suite sweep with the guard live surfaced exactly this one
call path (2 failing tests, 2041 passing). After repair: 70/70 across the
affected apps. Regression coverage in `apps/hr/test_hire_lock_hygiene.py` and
`apps/core/tests/test_blocking_io_guard.py`.

### R-02 — No database statement, lock or idle-transaction timeout  ·  HIGH  ·  CLOSED

**Where** `config/settings/base.py`

All three Postgres timeouts were at their default of zero, which means "wait
forever":

- `statement_timeout` — a query with a bad plan runs until somebody notices,
  holding a connection out of a small pool the whole time, so one slow page
  degrades every page.
- `lock_timeout` — a request waiting on a locked row waits indefinitely.
  Postgres detects and breaks true deadlocks; ordinary contention is not a
  deadlock and nothing breaks it, so the request simply never answers.
- `idle_in_transaction_session_timeout` — a wedged worker holds its locks and
  its snapshot until the process dies, and autovacuum cannot clean up behind it
  for as long as it sits there.

**Repair** 30s / 10s / 60s, env-overridable. Lock timeout deliberately shorter
than statement timeout: waiting on a lock is never progress, so it should give
up first and say so, rather than being cut off later by the statement limit
with a less specific error. Loosened under test (the scale harness builds
15,000 schools in one transaction) and idle-transaction disabled there
(`TestCase` holds a transaction open across each test).

The options string is **appended**, not assigned — a `DATABASE_URL` carrying
`?schema=` already writes a `search_path` into the same string, and overwriting
it would have pointed the application at the wrong schema without failing.

**Evidence** `apps/core/tests/test_database_timeouts.py`, asserted against the
live session (`SHOW statement_timeout`) rather than the settings dict, and
including a test that a runaway statement is actually interrupted and a lock
wait actually gives up.

### R-03 — Branch protection bypassed on push  ·  MEDIUM  ·  OPEN

Pushing `4e353629` and `2ee1af88` directly to `main` reported:

```
Bypassed rule violations for refs/heads/main:
- Changes must be made through a pull request.
- 4 of 4 required status checks are expected.
```

The protection exists so the required checks gate the commit. Bypassing it
means `4e353629` reached `main` with CI still running — and CI then failed.
Remaining audit work is on `audit/reliability-2026-07-26` for a PR, so the
checks gate rather than being worked around.

### R-04 — Three failure modes invisible to System Health  ·  MEDIUM  ·  CLOSED

**Where** `apps/core/health.py`, wired into the report as `data["platform"]`.

System Health covered twelve areas, none of them infrastructure. Three
conditions could hold indefinitely with nothing erroring and nothing on the
page saying so:

- **Migration drift.** A deploy that skipped its migrate step looks healthy on
  every page that does not touch the new column, then fails one page at a time
  as people reach the ones that do.
- **Delivery channel fallback.** A deploy that forgets `RESEND_API_KEY` falls
  back to the console mailer — by design, silently. Invitations and password
  resets stop arriving. **Since two-step verification shipped this is a
  lockout**: the code is only ever sent, never shown, so every enrolled account
  is shut out. The check names the count. The SMS check is a warning when
  nobody has enrolled on that channel and critical the moment somebody has.
- **Cache degradation.** Redis unreachable at boot falls back to `LocMemCache`,
  which works per-process — so cached figures differ between workers and the
  same page can show two different numbers depending on which one answers.
  Checked as a write and a read-back, because a cache that accepts writes and
  returns nothing is the failure worth catching and it does not announce
  itself.

**Evidence** `apps/core/tests/test_platform_health.py` — 16 tests, each check
exercised healthy *and* with the failure induced. A check that is green because
it cannot go red is worse than no check.

Note this is partly a risk the MFA work in `4e353629` introduced: before it,
undelivered email was an inconvenience.

### R-05 — The suite cannot tolerate a database flush  ·  MEDIUM  ·  MITIGATED

Adding `TransactionTestCase` classes for the timeout and guard tests broke two
unrelated tests hundreds of files away, and only in a full cumulative run —
they pass in every smaller combination I tried.

The mechanism is known in this codebase: a `TransactionTestCase` truncates
every table on teardown instead of rolling back, and reference data seeded by
migrations does not come back. A previous pass fixed this for specific apps
with idempotent `ensure_*()` hooks on `post_migrate`; the gap is that it was
fixed app by app rather than made structural.

The practical consequence is worth stating plainly: **nobody can add a
`TransactionTestCase` anywhere in this codebase without risking an unrelated
failure somewhere else, with nothing in the failure pointing back at the
cause.** That is a latent defect in the suite, not in the product, but it taxes
every future change that needs a real transaction.

**Now fixed structurally.** `apps/core/reference_data.py` is a registry; apps
register an idempotent ensure function and one `post_migrate` receiver runs
them all. What that buys is not the wiring — that was never hard — but that
`apps/core/tests/test_reference_data.py` can hold the convention to account:

- **Completeness.** Any app whose migrations create rows must either register
  or appear in `ONE_OFF_DATA_MIGRATIONS` with a written reason. A new feature
  cannot forget, because forgetting fails the build rather than a stranger's
  test next quarter. Proved able to go red by a test that injects a fictional
  unregistered app.
- **Idempotency.** Row counts before and after a second `restore_all()`, so an
  ensure function that duplicates on every flush is caught. Counted from the
  database rather than trusted from a return value — a function that
  under-reports would otherwise be indistinguishable from one with nothing to
  do, which is this whole failure moved one level up.
- **Restoration.** One `TransactionTestCase` whose entire job is to flush and
  confirm the rows came back.
- **No `serialized_rollback`.** Parsed with `ast`, so prose about it does not
  trip the check.

The investigation also found the problem in a **third** form. There was already
an `apps/core/test_seed_utils.py` with `reseed_migration_data()`, called
manually from `_post_teardown` by three `TransactionTestCase` classes — and it
held its *own copy* of the seed rows, with a comment noting they were
"duplicated (not imported)". So the five official target areas were defined in
three places: the migration, `apps/targets/reference.py`, and there. A weight
edited in two of the three would have produced a different Overall Progress
depending on whether the database had been flushed. It is now a shim
delegating to the registry; the three callers are untouched and still pass.

Its premise was also out of date: it reasoned that nothing restores data after
the *final* flush, which was true before those apps grew `post_migrate`
receivers. Django emits `post_migrate` after the teardown flush, so the
receiver covers it — and unlike the shim, it is not opt-in.

### R-06 — MFA API tests were passing for the throttle's reasons  ·  MEDIUM  ·  CLOSED

CI caught what local could not. `TokenApiTest` failed with `KeyError: 'mfaToken'`
because the login response was a throttle rejection, not a challenge: the token
API allows ten sign-in attempts a minute per IP, the window is process-global,
and every test in the class spends several.

Two of those tests were therefore passing for entirely the wrong reason. A test
asserting that a stolen password gets no token cannot tell a working second
factor from a rate limiter — it would have kept passing with the factor
removed.

Invisible locally because `.env` raises `RATE_LIMIT_LOGIN_PER_MIN` to 1000. The
class now clears the window in `setUp` and on cleanup, matching
`test_lockout_unification`. Verified by running with the CI value rather than
the local one: 106 accounts tests pass at 10/min.

Worth generalising: a local `.env` that loosens a production control makes
every test of that control vacuous, and nothing says so.

### R-07 — Two false positives I raised and withdrew

Recorded because a ledger that only lists confirmed findings hides the cost of
the method.

- The first version of the blocking-I/O guard assumed savepoint depth 0 meant
  "harness only". True under `TransactionTestCase`, wrong under `TestCase`,
  which already holds one — so it reported two ordinary password-reset sends as
  lock-holding violations. Both were fine. The guard now distinguishes the two
  harnesses by shape, and both directions are pinned by tests.
- A first scan for I/O inside transactions matched `advance_requests.` against
  the marker `requests.` and returned 11 hits, all spurious.

---

## Verified, no defect found

| Area | Method | Result |
|---|---|---|
| Outbound HTTP timeouts (§21) | Every module importing an HTTP client | Only 2 exist (`email.py`, `sms.py`); both bounded (15s, 10s) |
| Network I/O inside transactions (§12) | Runtime guard over full suite | 1 path found (R-01), now 0 |
| Locking primitives (§14/16) | Inventory | 83 `select_for_update` sites, 57 modules using `transaction.atomic`, 96 unique constraints |
| Dependency security (§51) | pip-audit, npm audit, CodeQL | 0 findings |
| Static security (§46) | bandit | 0 High, 0 Medium |
| Secrets in logs (§35) | Scan of every log call for credential-shaped arguments | none found |
| Runbooks (§40) | Written | `docs/runbooks.md` — 10 scenarios, each with detection, confirmation, containment, recovery, data-integrity check, owner and follow-up |

---

## Not executed

Stated plainly rather than folded into a score. None of the following was run,
so none of it can be reported as passing:

| Section | Item |
|---|---|
| 13 | Query-budget gate across all critical pages (exists for IA dashboard and the scale-invariance set only) |
| 15–17 | Idempotency, concurrency and deadlock tests across the full critical-mutation list |
| 27–30 | Load, stress and soak testing at production scale; safe-capacity documentation |
| 31–33 | File-upload, PDF-conversion and SSE failure matrices |
| 37–39 | Metrics endpoint, distributed tracing, alert definitions |
| 62 | The remaining System Health conditions: connection exhaustion, slow-query threshold, duplicate financial record, backup failure, security-scan failure, dependency vulnerability, performance SLO breach |
| 41 | Written threat model |
| 54 | Failure injection across dependencies |
| 55–59 | Backup restore rehearsal, disaster recovery, rollback rehearsal |
| 60 | Two consecutive full green CI runs, one without caches |

Three of these cannot be completed from this environment at all and need
infrastructure access: restore rehearsal into an isolated environment (§56),
disaster recovery (§57), and load/soak against a production-like deployment
(§28–29). The rest are executable here and are simply not yet done.

---

## Final verification

| Gate | Result |
|---|---|
| Full suite, cumulative order | 2072 passed, 0 failed |
| Full suite under the CI throttle value | accounts 106 passed |
| CI — Django Lint & Test Suite | pass |
| CI — Security Scans | pass |
| CI — CodeQL (python + javascript) | pass |
| `ruff check` / `ruff format --check` | pass |
| bandit / pip-audit / npm audit | 0 findings |

PR: https://github.com/O-Mario88/edify-planning-tool/pull/14 — all five required
checks green on `4fb63c02`.

---

## Go / No-Go

**NO-GO for production deployment.**

Not because of a known defect — R-01 and R-02 are closed with evidence, and
every gate that was run is green. It is a No-Go because section 63 makes
several conditions disqualifying on their own, and these currently hold:

- Restore is unverified (§56).
- Rollback is unverified (§59).
- Two consecutive full green CI runs have not been demonstrated for a release
  commit (§60).
- Load and soak results do not exist, so no critical endpoint has a measured
  p95 against its objective (§7, §26).

The readiness score cannot override those, and neither can the fact that the
test suite is green.
