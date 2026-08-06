# Runbooks

Each entry answers the same seven questions: how you find out, how you confirm
it is really that, what you do first to stop the bleeding, how you recover,
what you check afterwards to be sure no data was lost, who tells people, and
what has to change so it does not recur.

Written for the person who is woken up. Assume they know the platform but not
this incident.

**Standing rule for all of them:** the database is the source of truth. SSE,
cache, notifications and analytics are downstream. If they disagree with
Postgres, they are wrong and Postgres is right.

---

## 1. Web service down

**Detect** `/api/health/live` fails or the origin stops answering.

**Confirm** Curl liveness directly against an instance, bypassing the load
balancer. Liveness touches no database, so a failure here is the process, not a
dependency. If liveness answers and users still cannot reach the site, the
problem is upstream: DNS, load balancer, TLS.

**Contain** Confirm more than one instance is running. If one is wedged and
others are healthy, take the wedged one out of rotation rather than restarting
everything — restarting the healthy ones removes the capacity serving traffic.

**Recover** Restart the wedged instance. If every instance is wedged, look at
the deploy that preceded it before restarting them all; a crash loop restarts
into the same crash.

**Data integrity** None expected. A process that died mid-request rolled back;
`idle_in_transaction_session_timeout` reaps anything it left holding.

**Communication** Platform owner. Users see an outage, so say so.

**After** If it was a crash loop, the deploy gate did not catch it — add the
failing condition to the post-deployment smoke test.

---

## 2. Database unavailable

**Detect** `/api/health/ready` returns 503 with `{"db": "down"}`.

**Confirm** Liveness still answering while readiness fails is the signature.
That combination means the processes are fine and the database is not.

**Contain** Nothing to do at the application tier, and that is deliberate:
readiness failing removes instances from rotation without restarting them, so
capacity is intact the moment the database returns. **Do not restart the web
tier.** Restarting does not bring a database back and destroys the warm
capacity that would have served the recovery.

**Recover** Database owner's problem: failover, restart, or restore. The
application needs nothing beyond the database answering again.

**Data integrity** Check for financial records committed either side of the
outage: `Disbursement`, `PartnerPayment`, `AccountabilityRecord`. Run the
reconciliation check on System Health and confirm it reads zero difference.

**Communication** Database owner leads; platform owner relays to users.

**After** The Docker `HEALTHCHECK` points at liveness, not readiness, precisely
so a database blip does not restart every container. Confirm that is still
true — `apps/system_health/test_health_probes.py` asserts it.

---

## 3. Connection pool exhausted

**Detect** Requests time out while the database is healthy. `statement_timeout`
errors in the log. `pg_stat_activity` shows sessions at the connection limit.

**Confirm**

```sql
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
```

`idle in transaction` dominating means something is holding transactions open.
`active` dominating with long `query_start` means slow queries.

**Contain** `idle_in_transaction_session_timeout` (60s) reaps abandoned
transactions on its own. If a specific query is the cause, cancel it:

```sql
SELECT pg_cancel_backend(pid) FROM pg_stat_activity
WHERE state = 'active' AND now() - query_start > interval '30 seconds';
```

**Recover** Find what held the connections. The usual causes are a network call
inside a transaction (see runbook 4) and an unbounded query on a page that got
popular.

**Data integrity** Cancelled statements roll back. Confirm no partial workflow
rows: an `Activity` with cost lines but no schedule, a `FundRequest` with lines
but no header.

**Communication** Platform owner.

**After** If a query caused it, it needs a query budget. If a transaction
caused it, `apps.core.blocking_io_guard` should have caught it — work out why
it did not.

---

## 4. Email or SMS provider slow or down

**Detect** `edify.mailer` / `edify.sms` errors. Users report invitations,
password resets or sign-in codes not arriving.

**Confirm** Check System Health → Platform → Email Delivery. If it reads
`provider=console` in production, nothing has been delivered at all and nothing
was erroring — the console provider is the silent fallback.

**Contain** **This is a lockout, not an inconvenience.** Accounts with two-step
verification cannot sign in while email is down: the code is only ever sent,
never shown. If it will be down for a while, set `MFA_REQUIRED_FOR_ALL=false`
and unset `mfa_enabled` for the affected accounts so they can get in with a
password. Record that you did it — it is a deliberate, temporary reduction in
control.

**Recover** Restore the provider. Sends are not queued; a failed send is lost.
Password resets and invitations can be re-issued from Admin → Users. There is
no resend for a two-step code beyond the person signing in again.

**Data integrity** None. Sends happen after commit, so a failed send never
means a half-created account.

**Communication** Platform owner. If two-step accounts were affected, they need
telling directly — they cannot be reached by email.

**After** Delivery failure is currently only a log line. If this happens twice,
it needs an alert.

---

## 5. Scheduler stopped

**Detect** System Health → Background Automation shows a job stale past its
`max_interval_minutes`.

**Confirm** Check `ScheduledJobExecution` for last attempted and last
successful time per job. A last-attempt that is recent with no success is a
failing job; no attempt at all is a dead scheduler.

**Contain** Jobs are idempotent by design and locked by `ScheduledJobLock`, so
a manual re-run is safe. Nothing needs to be held back.

**Recover** Restart `python manage.py runscheduler` — the dedicated process,
not the web workers. A job that runs in every web worker is the defect this
separation exists to prevent.

**Data integrity** Per job. Weekly Fund Request upserts by (week, owner).
Monthly Work Plan upserts by (country, month). Target Ledger Sync rebuilds from
source. All safe to re-run. Confirm no duplicate `FundRequest` for the affected
week.

**Communication** Platform owner. If a weekly fund request was missed, finance
needs to know before their cycle.

**After** A scheduler that can stop without anyone noticing until a job is
stale needs its own liveness signal.

---

## 6. Duplicate payment detected

**Detect** Reconciliation mismatch, or a partner reporting being paid twice.

**Confirm**

```sql
SELECT activity_id, partner_id, count(*), sum(amount)
FROM partner_payment
GROUP BY activity_id, partner_id HAVING count(*) > 1;
```

**Contain** **Stop the payment run.** Do not attempt to reverse anything in the
application until the extent is known — a partial reversal is harder to
reconcile than the duplicate.

**Recover** Establish which record is authoritative (earliest `created_at` with
a NetSuite reference). Record the correction through the normal reversal path
so it carries an audit row and a reason. Never delete the duplicate: a deleted
row is indistinguishable from one that never existed.

**Data integrity** Reconcile the affected partner and period to UGX 0. Check
`FinanceAuditLog` for both records and confirm each has an actor.

**Communication** Finance lead owns this one. It is a financial incident, not
just a technical one.

**After** A duplicate that reached the database means uniqueness was not
enforced there. A guard in application code is not sufficient — the constraint
belongs on the table.

---

## 7. Failed deployment

**Detect** Post-deploy smoke test fails, or errors spike immediately after a
release.

**Confirm** Compare the running commit to the intended one. Check System Health
→ Platform → Migration Drift: a deploy that skipped its migrate step looks
healthy on most pages and fails one at a time as people reach the ones that
touch the new column.

**Contain** Roll the application back to the previous image.

**Recover** Application rollback restores code, static assets, workers and
scheduler. **Database rollback is a separate decision and is usually the wrong
one.** If the migration was additive, leave it — old code ignores a new column.
If it was destructive, forward-repair rather than reversing.

**Data integrity** Any workflow that ran against the new schema between deploy
and rollback needs checking by hand. Establish the window from the deploy
timestamps and audit rows in it.

**Communication** Platform owner. Say which window is affected.

**After** Additive-then-destructive across two releases, never both in one.

---

## 8. Leaked credential

**Detect** Secret scanning alert, or a key found in a log or a repository.

**Confirm** Establish what it opens and how long it has been exposed. Assume
the whole exposure window, not the time since discovery.

**Contain** **Revoke first, investigate second.** A rotated key cannot be used
while you work out whether it was.

**Recover** Rotate in every environment. If it was `JWT_SECRET`, every session
and refresh token is invalidated — expect everyone to be signed out, and say so
before they notice. If `FIELD_ENCRYPTION_KEY`, do not rotate before confirming
what it decrypts, or the data becomes unreadable.

**Data integrity** Check `AuditLog` across the exposure window for actions from
unexpected addresses. The chain is hash-linked; verify integrity rather than
trusting it.

**Communication** Security owner leads. Removing the file is not remediation
and must not be reported as such.

**After** Add the pattern to secret scanning. Understand how it got committed.

---

## 9. Cache unavailable

**Detect** System Health → Platform → Cache is critical, or the site is
uniformly slow with a healthy database.

**Confirm** The check does a write and reads it back. A cache that accepts
writes and returns nothing is the failure that matters, and it does not
announce itself.

**Contain** Nothing. Everything falls back to Postgres and stays correct,
because nothing authorization-bearing is cached. The site is slower, not wrong.

**Recover** Restore Redis. Note that `SESSION_ENGINE` is chosen at boot from
whether Redis answered, so a process started while Redis was down uses the
database backend until restarted — sessions keep working either way.

**Data integrity** None. The cache holds no authoritative state.

**Communication** Platform owner if the slowdown is user-visible.

**After** If it degraded to LocMemCache rather than failing, cached figures
were per-worker for the duration — the same page could show two different
numbers. Check whether anyone made a decision on one.

---

## 10. High latency, no errors

**Detect** p95 above objective with a flat error rate.

**Confirm** Find whether it is one endpoint or all of them. All of them points
at a shared dependency: database, cache, connection pool. One points at that
page's own queries.

**Contain** If one page is responsible and it is not urgent work, it is
legitimate to take it out of the navigation for the duration rather than let it
consume the pool.

**Recover** For a single page, get its query count and compare against its
budget. The usual causes are an N+1 that arrived with a new field on a template
and a filter that stopped using an index.

**Data integrity** None.

**Communication** Platform owner.

**After** A page that regressed without a failing test needs a query budget —
that is what makes the regression visible at the point it is written rather
than in production.
