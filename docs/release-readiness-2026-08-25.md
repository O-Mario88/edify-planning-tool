# Release Readiness Assessment — 2026-08-25

**Verdict: NO-GO for a 2026-08-26 production rollout.**

Baseline commit `e13dce8`. Audit run from a source-only container with PostgreSQL 16,
no Redis, no Docker daemon, and no access to the production environment.

This is not a judgement that the platform is poor. It is a well-engineered system with
unusually honest internal controls, and the audit found several defences better than most
production codebases carry.

**Twenty-eight entries in §4's fixed table were closed in this audit**, including three P0s — a rescheduling
path that could CASCADE-delete a disbursed advance, migrations that could run concurrently
with no lock, and an IA certification service that asserted no authority at all, so any of
the fourteen roles could stamp work verified. Every fix carries a regression test verified
to fail before it and pass after. §4 lists them.

**All twenty-two mandated end-to-end journeys are now enumerated as data, and twenty are
walked by a single test each.** The two that are not are blocked on the only two findings
an audit cannot close by writing code. Walking them is what found four of the fixes,
including two that no surface would ever have complained about: a Special Project whose
impact could never be measured, and an accountability record no CCEO could ever clear.

**Those twenty are also now traced to the code that runs for them**, by the requirements
traceability matrix (§11, §45.2) — the last of the twelve mandated deliverables, deferred
by two prior audits and built here. It asserts nothing: it executes each journey's own test
with the platform instrumented and records the routes, services, models, permissions,
notifications, audit actions and metrics the run genuinely touched. Doing that immediately
produced a finding about the evidence itself — **JRN-01**: not one of the twenty journeys
issued an HTTP request or computed a registered metric. The platform's 810 route-level
authority gates were exercised by no mandated journey at all, and neither was any number
a user is actually shown. The door is proven, the domain is proven, the display is
proven, and nothing proved they meet — which is precisely where SEC-01, the one live
privilege escalation found here, turned out to live. Two journeys have since been taken through the door: journey 19 reproduces SEC-01 at
the endpoint it lived at, and journey 7 — the money path — **found a defect on its
first run**, an API endpoint that had never worked in a codebase with 6,081 passing
tests (FIN-06). The other eighteen are still below the door. See §4b.

What remains is not a list of defects nobody has looked at. The No-Go rests on three
things a deadline cannot convert into evidence:

1. **Nine mandated gates cannot produce evidence from any source-only audit** — backup
   restoration, rollback rehearsal, deployment rehearsal and production smoke among them.
   No restore from a production backup has ever been performed. The mandate's own rule is
   that Not Tested is never Green.
2. **Three questions need the product owner, not an engineer.** Whether the Country
   Director's dashboard or the Programme Lead's is the truthful one (CONFLICT-001, where
   both fix directions break tests encoding the other behaviour); whether Impact Assessment
   should author the priorities it verifies against (CONFLICT-002); and whether Salesforce
   reconciliation stays a manually typed reference.
3. **Two capabilities the release scope names do not exist**: offline field operation, and
   a Core Assessment nobody can schedule because no catalogue item costs one. The second is
   a Country Director configuration decision rather than a build, and the platform now
   reports it instead of blaming a school for it.

None of the three is closable by more code review. Each needs an environment, a decision,
or a work programme.

**A note on how the fixes were found, because it bears on how much this report is worth.**
Six of the twenty-four came from walking journeys end to end rather than from reading code,
and every one of those six lived at a seam between two subsystems that were each correct.
The recurring defect this platform produces is not a wrong calculation — the calculations
are unusually careful — it is *a designed capability with readers and no writers*: a
register three pages read and nothing fills, a figure that links to a table nothing writes,
a measurement function nothing calls. Four findings of that shape were raised here —
GOV-01, FIN-05, PROJ-01 and GOV-02 — and the first three are closed. A repo-wide census now
pins every model that remains in that state, with a written reason each, so a fifth cannot
appear in silence (§4a).

JRN-01 is the same shape one level up, and worth reading that way: the journey evidence has
scrupulously honest readers — every test passes, every count is true — and the layer it
does not reach was simply never something anyone's instrument pointed at. It took an
instrument that records what *ran*, rather than what passed, to see it.

---

## 1. Gates executed in this audit

Everything in this table was run, not inferred.

| Gate | Command | Result |
| --- | --- | --- |
| Ruff lint | `ruff check .` | **PASS** |
| Ruff format | `ruff format --check .` | **PASS** (1,492 files) |
| Migration drift | `makemigrations --check --dry-run` | **PASS** — no changes detected |
| Production boot gate | `manage.py check --deploy` (prod settings) | **PASS — fails closed** |
| CSS bundle reproducibility | `npm run build:css` + `git diff --exit-code` | **PASS** — byte-for-byte |
| Design-system / mobile contracts | 101 contract tests | **PASS** |
| Full test suite | `manage.py test` | **PASS** — 0 failures, 0 skips, 3 documented expected failures (CONFLICT-001 and the two halves of DEP-01), each quarantined at the test and self-removing |
| 50,000-school scale | `test_load_scale` @ 50k, quiet machine | **PASS** — 21 tests |
| Readiness honesty | live probe, Redis genuinely down | **FAIL** (RC-001) |
| E2E journey census | `test_release_journey_census` | **PASS as a census; 20 of 22 walked** — nothing unwritten, 2 blocked on FE-01 and INTG-01 |
| Role × surface authorization matrix | `manage.py build_permission_matrix` + `test_permission_matrix` | **PASS** — 1,028 surfaces, 845 guarded and answered role by role, 183 declaring none and listed, 0 reachable by nobody |
| Requirements traceability matrix | `manage.py build_traceability_matrix` + `test_traceability_matrix` | **PASS as a build; it found JRN-01** — 22 requirements, 20 traced by executing their own test, 2 blocked. Every traced row records what actually ran. Route column empty on 19 of 20 and metrics-computed column empty on all 20: see JRN-01 in §4b |
| Container vulnerability scan | Trivy, in CI | **Fix pushed; awaiting the next run** — passed twice on 2026-08-25 and again on `54e3cc8`, then failed from `e815d04` on a new upstream CVE (DEP-08). The base-image packages are now pinned forward; CI's own image build is the verifier |
| Branch CI on the fixed tree | GitHub Actions, head `fe75c79` | **PASS** — all five jobs, whole workflow green |
| Seed-command safety | code audit of the only hard-delete path | **PASS — three guards** |

**The container scan has since started passing, and this section said otherwise.** Through
the morning of 2026-08-25 the Security Scans job failed at one step, `Scan the image`, on
every commit — and identically on `main` at `e13dce8`, this branch's baseline, which is how
it was established as not this branch's doing. The findings were OS-package CVEs in the
base image (`util-linux` and `mount`, CVE-2026-53612 through -53615), none carrying a fixed
version at the time, which is why it was recorded as needing a base-image refresh rather
than a code fix.

At 08:38 on the same day it passed, on run 910 (head `693530f`) — the whole workflow green,
every job including `Scan the image`. Nothing in this branch touched the Dockerfile or the
dependency pins, so what changed was upstream: the fixed packages landed, or the scanner's
database did. The earlier FAIL is kept here rather than deleted, because a blocker that
resolves itself is worth being able to see resolve.

**And on 2026-08-26 it went red again, on a different CVE, which is why this row now reads
FAIL.** The scan passed on `54e3cc8` at 06:12 and failed on `e815d04` at 07:14. The finding
is **CVE-2026-14456** — an OpenSSL denial of service through unbounded memory growth in the
QUIC server path, HIGH — against three Debian 13.6 base-image packages: `libssl3t64`,
`openssl` and `openssl-provider-legacy`, installed at `3.5.6-1~deb13u2`.

It is not this branch's, and that is established rather than assumed: the diff between the
green head and the red one contains **no Dockerfile, no requirements file, no CI workflow
and no package manifest** — 4,439 lines of Python and Markdown and nothing else. An
OS-package CVE in the base image is not reachable from that diff. What changed in the
sixty-two minutes between the two runs was the vulnerability database.

**This one differs from the August 25 failure in the way that matters: a fixed version
exists.** Trivy reports the status as `fixed`, with `3.5.7-1~deb13u2` available. So unlike
the `util-linux` finding, this is closable now rather than blocked on upstream. The
Dockerfile builds `FROM python:3.13-slim` and runs `apt-get update && apt-get install`
without an upgrade step, so the runtime image carries whatever OpenSSL the base image tag
shipped with. The fix is a base-image refresh or a targeted upgrade of those three packages
in both stages.

**The fix is now applied, and the reason it could be is worth stating.** For several
commits it was not: this environment has no Docker daemon and no Trivy, and a change to the
production runtime image that cannot be built, run or re-scanned before pushing is a fix
marked resolved because code was committed — the one thing the mandate names outright. So
it was recorded here and on the pull request with the proposed patch instead.

What changed is not the environment but the verifier. **CI's Security Scans job builds this
image and scans it** — that is the job reporting the failure. A Dockerfile change pushed to
this branch is therefore checked by exactly the gate it is meant to clear, on a machine that
can do what this one cannot. Combined with the product owner's decision that the rebuild
happens *before* go-live rather than after, the objection no longer holds.

The runtime stage now names `libssl3t64`, `openssl` and `openssl-provider-legacy` in its
existing `apt-get install`. Nothing here links against them directly — the base image
already carries them — but naming them is what gives apt a reason to take the newest version
the archive has rather than whatever the tag froze. Deliberately narrow rather than
`apt-get upgrade`, which would change more than the finding asks for on an image nobody can
re-test between build and deploy.

**The gate is Not Tested until CI says otherwise.** If the scan still reports the finding,
the fixed package is not yet in the archive the base image points at, and that is a
different problem with a different answer — recorded rather than assumed either way.

**On CI coverage of the most recent work — a gap that was real and is now closed.** Runs
911 through 915 were each *cancelled* by the next push rather than completing: pushing
every journey as its own commit meant each run superseded the one before it, so for a
while the newest CI evidence on this branch predated SEC-03 and Journeys 9 and 22. That
was recorded here as an evidence gap rather than covered by the earlier green.

It is closed, twice over. Run 916 on head `fe75c79` completed with every job green, and
run 935 on head **`304b0ce`** — the head this assessment describes — completed with **all
five jobs green**: Django Lint & Test Suite, Security Scans (including `Scan the image`),
CodeQL, `Analyze python` and `Analyze javascript-typescript`. That second run is the one
that matters, because it is the first fully green CI on a head carrying every fix and every
journey walk in this report, and it is the fourth independent execution of this code to
disagree with run 932.

The lesson is worth keeping: a branch that is pushed to faster than CI can run is a branch
whose CI status is always about an older commit than the one you are looking at. Pushes
were paced after that, in batches rather than per commit.

**Two CI runs failed the Django job, and this report first said one.** The correction
matters, because one failure with three passing executions around it reads as noise and two
failures reads as a pattern — and the second reading is the one that gets investigated.

The first, run 931 on head `210318a`, **was a real regression and is fixed**. CORE-01's
first version refused the unsendable core-assessment ask outright, which took away a
Programme Lead's ability to send any oversight action on a core school whose only other
blocker was the package. The local full suite caught it as exactly one failure —
`test_the_supervisor_can_send_an_action_to_the_responsible_cceo`, a test titled for what a
supervisor "must NOT lose" — and commit `29faf89` fixed it by falling through to the
resolvable ask. CI was failing for the same reason at the same time.

The second, run 932 on `9a201c4`, has no such explanation and is contradicted by three
independent executions of identical Python: the local full suite on that exact tree at
6,037 tests, and CI runs on `e3b3a79` and `e024d5e`, which differ from it only under
`docs/`. It is recorded as unexplained rather than as a flake. The distinction is not
pedantry — "it went green on the retry" is the sentence that hides real intermittency, and
what makes this one safe to set aside for now is that the passing runs are of the same tree
rather than of a fix.

The failing test's name is not in this report because it could not be read from here: the
MCP job-log tool returns only the Postgres service container's tail, and the full-log
artifact host is denied by the environment's network policy. That is a limitation of the
audit environment, stated rather than papered over, and it is the reason this entry says
"unexplained" instead of naming a cause.

**The suite grew with the work and stayed clean.** It ran at 5,951 tests when this section
was first written, 6,037 at the last full run before the DEP-01 guard was added, and
**6,081 at HEAD `8739af6`** — `OK (expected failures=3)` in 3,600s, with no failures, no
errors and no skips. Expected failures appear only where a defect is deliberately
quarantined — CONFLICT-001 and the two halves of DEP-01. Each is self-removing.

That HEAD run was corroborated rather than trusted: CI's Django Lint & Test Suite passed on
the same commit, on a different machine, in 21 minutes. Two independent executions of the
same tree agreeing is what the count above rests on — which matters here, because run 932
on `9a201c4` remains the one Django failure this audit could never reproduce or explain.
The GOV-01 guard's expected failure is gone because the gap it marked was closed: it
reported an UNEXPECTED SUCCESS on the run after the write path landed, which failed the
build and forced the marker off, exactly as its docstring said it would.

Suite size at HEAD: **438 test files; the runner collected and ran 5,948 tests.** The run
on the fixed tree is clean — `OK (skipped=0, expected failures=1)` in 923s. The single
expected failure is CONFLICT-001 below, quarantined deliberately and documented at the
test.

### Both skips were hiding something, and this report first said otherwise

An earlier draft of this section disposed of the run's two skips as "conditional on data
the dev database does not hold" — which is what the skip messages implied, and which was
not checked. Running the suite at `-v 2` to name them found that neither was benign, and
that the sentence dismissing them was exactly the false-green reasoning the mandate
forbids. Both are now closed and the suite skips nothing.

**`test_the_cost_does_not_grow_with_the_number_of_program_leads`** measured the growth,
saw it, and called `skipTest` on itself with the measurement in the message. A test that
detects a regression and then declines to fail reports green over an open defect for as
long as it exists. The defect was real: `_pl_cceos` was memoised per Programme Lead, so
each additional one cost three more queries on every Country Director surface that walks
the list. Measured on `/todos`: **82 queries at three Programme Leads and 112 at
eighteen**. Batching the resolution onto the scope object makes it **69 at both**. The
test now measures the request rather than calling the service directly — the distinction
mattered, because outside a request `apps.core.request_cache` is deliberately inert, so
the direct path pays a per-user re-read that no page load pays, and the test could not
tell that policy apart from a regression. Verified by reverting the fix: 82 → 112, failed;
restored, passes.

**`test_monthly_fund_plans_are_counted_not_just_weekly_advances`** asserted that the FY
money totals exceed the weekly-advance totals whenever a monthly plan exists. That was
true when the totals summed both snapshots, and D1 moved them to the `AdvanceRequest`
ledger precisely because that addition counted a cost line requested through both channels
twice. Under the ledger the assertion asks for the double-count back. It skipped whenever
the database held no monthly plan, which was always, so nothing ever caught it going
stale. Removed, with the rule it named left where it is genuinely exercised
(`test_audit_funding_channels.test_fy_totals_count_the_shared_cost_line_once`, which seeds
both channels).

### The scale gate needed two runs, and the first one would have been a false alarm

Run at `EDIFY_SCALE_SCHOOLS=50000 EDIFY_SCALE_GROWTH=10000`. Measured p95 at 50,000
schools on a quiet machine, every surface inside its objective:

```
/dashboard=508ms  /my-plan=95ms   /schools=451ms      /todos=227ms
/analytics=825ms  /settings=28ms  /notifications=44ms /system-health=12ms
```

Scale-invariance also held on every surface — query counts do not move as the estate
grows, which is the stronger claim than any single latency figure.

The first run of this gate **failed** its latency objective (`/dashboard` 900ms,
`/todos` 1408ms, `/analytics` 1631ms) because it executed while nine audit workstreams
were running tests concurrently: load average 8.90 on 4 CPUs. Reporting that as a
performance regression would have been wrong by a factor of up to six. It is recorded here
because the lesson generalises — `docs/audit-2026-08/02-scale.md` makes the same point
about its own figures, and a latency number is only evidence if you know what else the
machine was doing.

### The production boot gate is a strength worth naming

`config/settings/prod.py` refuses to start without `AUTHZ_MODE=enforce`, the five
`SPACES_*` values, `SUPER_ADMIN_PASSWORD` and a valid `FIELD_ENCRYPTION_KEY`. A
misconfigured production deploy fails loudly at boot instead of silently serving with
uploads going nowhere. Verified by running it.

### The seed command cannot destroy production

`_purge_operational()` runs `Activity.objects.all().delete()`, which would CASCADE
through evidence, verification records, Salesforce references and cost lines
(`apps/evidence/models.py:16`, `apps/activities/models.py:631,653`). It is reachable
only under `--demo`, behind three independent guards — including one that asks the
**database** for its own environment stamp and refuses if it says `production`,
"regardless of what this process believes it is"
(`apps/core/management/commands/seed.py:143-154`). That defends the case that actually
happens: a local shell whose `DATABASE_URL` points at the live database. This is
better than most systems manage.

---

## 2. What this environment could not verify

| Gate | Blocker |
| --- | --- |
| Backup restoration tested (§35) | No managed-Postgres access |
| Rollback rehearsal (§43) | No deploy target or prior image |
| Deployment rehearsal (§39) | No deploy target |
| Production smoke test, 27 steps (§42) | Proxy denies edifyplanning.app |
| Live integration failure/recovery (§30) | No Salesforce / NetSuite / MFI endpoints |
| Real-device mobile (§33) | Emulation only |
| Observed 15-minute field objective (§34) | Requires time studies with real users |
| Production monitoring + incident owner (§44) | Requires the live stack |
| Load/concurrency at production scale (§34) | No load generator against production |

Nine gates. Under §6.4 none may be marked Green, however good the code is. A real Go
decision requires a staging environment and the deployment path; it cannot be issued
from a source-only audit.

---

## 3. Prior audit evidence has expired

The repository contains a rigorous internal audit at `docs/audit-2026-08/`, dated
2026-08-16, which recorded honest gate statuses (1 of 16 journeys, offline not
assessed, backup restore not assessed, 50 of 68 metrics disagreeing).

Since that baseline: **52 commits, 647 files changed, 122,538 insertions, 19,532
deletions.** Route count has moved from the 952 that audit walked to **1,028** at HEAD
— 76 routes it never saw.

Its PASS verdicts — including "all 952 routes walked; no unguarded state-changing
endpoint" — describe a codebase that no longer exists. They cannot be carried into this
release candidate without re-verification, and re-verification of that scope did not
happen in this audit either.

---

## 4. Release-blocking findings

Full detail, including the workstream reports, follows in §6.

### Fixed in this audit

Every entry below carries a regression test verified to fail before the fix and pass
after. Where a test initially passed against the unfixed code it was
rewritten, not accepted.

| Sev | ID | Finding |
| --- | --- | --- |
| P0 | FIN-01 | The cost-snapshot lock had drifted two statuses behind `MONEY_MOVED_ADVANCE_STATUSES`, so rescheduling could CASCADE-delete a **disbursed** advance |
| P0 | DEP-02 | Migrations could run concurrently with no lock, making `instance_count: 1` load-bearing |
| P1 | SEC-01 | The school edit drawer gated its write on the READ helper, letting a Programme Lead take ownership of a supervised CCEO's school |
| P1 | INTG-05 | "Partner Payments Pending" counted `completed`/`closed` work carrying no IA verification as verified-and-payable |
| P1 | D2 | Approving leave granted the absent person's portfolio, supervisee scope and approval authority to a cover who had **declined** |
| P1 | FIN-03 | Two partner-payment paths had no `payment.act` gate and the service checked nothing at any layer |
| P1 | FIN-02 | `reimburse()` took any amount unvalidated; the settlement identity was checked only after payout, with no reversal |
| P1 | TGT-02 | Cancelling or deferring work left its verified achievement credit standing |
| P1 | TGT-01 | Ratio milestones were allocated without the denominator their arithmetic needs, and scored 0% for ever |
| P1 | TGT-03 | Annual "unique schools" figures summed per-month distinct counts, double-counting a school reached twice |
| P1 | D8 | The follow-up SSA that qualifies a champion candidate set a status that hid its plan from the scorer |
| P1 | INTG-02 | Nothing pushed when a scheduled job failed or stopped |
| P1 | INTG-03 | Six paths wrote notifications with no `source_event_type`, so they could never auto-close and were promoted to urgent |
| P1 | INTG-04 | 18 registered metrics named service callables that do not exist |
| P1 | INT-01/02, INTG-07 | No DB CHECK constraints on money outside one app; no uniqueness on the NetSuite id gating finance clearance |
| P2 | RC-001 | Readiness answered `{"status": "ok"}` with Redis genuinely down |
| P2 | SEC-02 | `can_update` claimed every write resolved through it; nothing called it, which is how SEC-01 survived a green suite |
| P2 | D3/D4 | API leave decisions notified nobody; accepting coverage claimed a notification it never sent |
| P2 | D6/D7 | Core slots completed through the real path carried neither evidence nor Salesforce id, so two blockers alarmed for ever |
| P0 | SEC-03 | `certify_activity` asserted no authority at all — every one of the fourteen roles could stamp an activity IA-verified. "False IA verification" is a P0 by name |
| P1 | FIN-04 | Money disbursed against work later **cancelled** could never reach a settled state — finance clearance required IA verification, which called-off work can never obtain |
| P2 | ISSUE-007 | Two tests skipped themselves rather than fail, so the suite reported green over an open N+1 and a stale assertion. See below |
| P1 | FIN-05 | The Accountant's **Returned** money figure linked to a queue reading a table nothing writes; its empty state read "All corrections resolved" beneath a live returned balance |
| P1 | PROJ-01 | `refresh_follow_up` had no caller, so no Special Project could ever report a measured school — and the reminder designed to chase the missing assessment could never fire either |
| P1 | GOV-01 | **Both** Business Transformation school-assessment registers were read-only — three surfaces read each, nothing wrote either. The government-requirements register a Country Director opens was structurally empty for every school |
| P1 | CORE-01 | The Core package's assessment blocker was a **critical nobody could ever clear**, sent as an accountability record to a CCEO the platform gives no way to act |
| P3 | — | The partner role-bridge failed **open** when its flag was absent |
| P2 | FIN-06 | The Accountant's approval endpoint **returned 500 to every caller, always** — the step where an over-spent advance becomes a reimbursement claim, unreachable over the API since it was written |

**The shape most of these share.** One definition, written out in several places, where a
copy drifted: the money-moved status set, the rate-measurement set, the school-write rule,
the metric service pointer, the notification writer. In each case the fix names the
definition once and makes the copies read it, and three guards were added so the drift
cannot recur — the cost-snapshot test parametrises over its constant, the metric registry
resolves every service path, and a scanner fails on a raw `Notification.objects.create`
outside the notifications app.

**ISSUE-007 has a different shape, and a worse one.** It was not a drifted
copy but a test that measured a regression and then chose not to fail — and a second that
had quietly outlived the rule it asserted. Neither was hidden: both printed their reason
in the run. What hid them was that a skip reads as a pass in every summary line anyone
looks at, including the one in this report's first draft. A defect a test declines to
report is worse than one no test covers, because the second is visibly absent from the
coverage and the first is not. The suite now skips nothing, which makes any future skip
a signal rather than noise.

### FIN-06 · The Accountant's approval endpoint has never worked

**P2 · fixed in this audit · found by taking journey 7 through the door**

`POST /api/fund-requests/advances/<id>/account-approve` raised `TypeError` and returned
**500 to every caller, always**. It is the step where an over-spent advance becomes a
reimbursement claim — on the platform's only path where money leaves the organisation a
second time for the same activity.

The cause is three lines in `_advance_view`, the factory that turns an advance service
call into a permission-gated endpoint. Its `takes_data=False` flag meant "pass an empty
dict" rather than "pass no dict", so `approve_accountability(advance_id, principal)` — two
parameters — was handed three. The flag has exactly one user, which is why exactly one
endpoint was broken.

The line immediately above it is the tell. `AdvancePlApproveView` wraps *its* two-argument
service in a lambda that swallows the payload. The same arity problem, noticed and solved
correctly one line earlier, and not noticed here.

**Severity is P2, not P1, and the reason matters.** The frontend door works:
`finance_views.py:456` calls `approve_accountability(adv.id, request.user)` with the right
arity, so a real Accountant clearing accountability in the UI was never affected. What was
broken is the API — routed, permission-gated, in the published surface, and returning 500
to any integrator who called it. No money was mis-moved and nobody was blocked.

**Why 6,081 tests did not catch it.** They never issued an HTTP request to it. The service
beneath is correct and well covered; the view is routed and gated; only the *join* had
never been executed by anything. A smoke test does exercise
`/api/fund-requests/<id>/account-approve` — but that is the weekly fund request's endpoint,
a different view on a similar path, and its passing said nothing about this one.

This is JRN-01's thesis demonstrated on its first application. The prediction was that
defects live between the door and the service and that no mandated journey looked there.
The first journey taken through the door found one within minutes.

Fixed by making the flag mean what it says. Verified by mutation: restoring the original
two lines turns `test_the_same_overspend_walks_the_real_endpoints` red with the same 500.

### Still open

Nothing below is now a defect nobody has looked at. Each is either infrastructure this
audit cannot reach, a build, or a decision that is not engineering's to take.

| Sev | ID | Finding | Why it is still open |
| --- | --- | --- | --- |
| P0 | DEP-03 | No restore from a production backup has ever been performed | Needs the managed database. The rehearsal harness exists and is rigorous |
| P0 | DEP-01 | The repository's two records of the live app describe **two different applications**, by UUID | Needs `doctl apps spec get`. Now quarantined by `test_deployment_record_is_singular`, and the asymmetry between the two records is recorded — see §6.1 |
| P0 | INTG-01 | No Salesforce, NetSuite or MFI transport exists | Needs credentials, or a scope decision that reconciliation stays manual |
| P1 | CONFLICT-001 | CD dashboard reports 200% where the PL correctly reports 0% | **Product decision.** Both fix directions break tests encoding the other behaviour |
| P1 | FE-01 | Offline field operation does not exist | A build: IndexedDB queue, replay, server-side idempotency keys |
| P1 | RC-003 | 20 of 22 mandated end-to-end journeys have a real test | The two that remain are blocked on the only two findings an audit genuinely cannot close by writing code: FE-01, which is a build, and INTG-01, which needs credentials or a scope decision. The 22 are enumerated and the count machine-checked |
| P1 | JRN-01 | **18 of 20** walked journeys still issue no HTTP request, and none computes a registered metric, so most of the **810 route-level authority gates** and every displayed number are exercised by no mandated journey | An evidence gap this audit produced, named, and is closing one journey at a time. Journey 19 sweeps four endpoints as all thirteen roles and reproduces SEC-01 where it lived; journey 7 walks five money endpoints and **found FIN-06 on its first run**. Both mutation-verified. The remaining eighteen are the open part. Pinned in both directions by `WhichJourneysReachTheDoorTest` — see §4b |
| P1 | DEP-08 | **CVE-2026-14456** (OpenSSL QUIC denial of service, HIGH) in the production runtime image | Upstream base-image CVE, not this branch's: the diff between the last green scan and the red one was Python and Markdown only. **Decided and fixed** — the product owner chose to rebuild before go-live, and the runtime stage now pins the three OpenSSL packages forward. CI's own image build and scan is the verifier; open until that run is green |
| P1 | DEP-05/06/07 | No log retention, no error tracker, two alert rules, no named incident owner | Configuration and an org decision. The scheduler half is now fixed |
| P1 | D5 | `CorePlan.assessment_completed` is unreachable by any route | **A costing decision, not code.** No catalogue item carries `core_assessment_visit`, and adding one means naming what a Core Assessment costs. The costing layer says so itself: an unknown profile raises "Country Director configuration must be repaired before scheduling". Its user-visible half is fixed — see CORE-01 |
| P2 | GOV-02 | **One** workspace a user can navigate to can never hold data: the Maintenance Calendar. Its empty state says templates are not configured "yet", and the health check beside it reports Maintenance Generation ok, permanently | A build, or a decision to retire it as three sibling pages already were. See §4a |
| P2 | GAP-02 | IA cannot edit Master Priority rows | **Not unbuilt — built the other way, deliberately.** The matrix gives IA import/allocate/view and withholds edit/define; the cascade explains why. Recorded as CONFLICT-002 |
| P2 | FE-02 | KPI headline limit enforced at 6, not the stated 4 | Needs the owner to say which number is the rule |
| P2 | D6 (closure) | "Package Complete" is a status nothing writes | Inventing the closure workflow is a product decision |
| P3 | RC-002 | `AUTHZ_MODE` branches nothing at runtime, and `security.summary()` still reports `authzMode` over the API | Smaller than first recorded: no template renders it, and production **cannot boot** unless it is `enforce` (`config/settings/prod.py`). Object-level authz is unconditional either way, so the field describes a boot assertion rather than a mode |

## 4a. Every model that is read somewhere and written nowhere

GOV-01 was found by walking one workflow. The question it raised is whether it was one
mistake or a habit, and that question has an answer the codebase can be asked directly:
which concrete models does something read, and nothing write?

Eighteen came back. They are worth reporting one by one, because the categories differ
more than the count suggests, and because three of them are the strongest available
evidence that the method works.

**Three were already found, by three earlier passes, and handled three different ways.**
`MonthlyFundRequest` — `budget_views.py` carries a comment calling it "the legacy
MonthlyFundRequest row that nothing in this codebase ever writes to (it would otherwise
show 'Draft' forever — a fake status)", and reads the live `FundRequest` instead.
`ReimbursementClaim` — `navigation.py` de-links the queue with a paragraph explaining
that keeping the link "would be a permanent-empty-state trap for every Accountant".
`EmployeeComplianceRecord` and `PayrollReadinessRecord` — the HR dashboard renders an em
dash rather than 0%, because "a percentage over an empty table is not 0% — it is 'we have
not recorded any of this yet'. Rendering it as 0% told HR they were failing a check
nothing in the platform can currently populate." A scan that rediscovers, from nothing,
three defects that three separate audits found by hand is a scan that detects the class
and not the instance.

**One was new, and it is the reason this section is not an inventory exercise.** FIN-05:
the Accountant's home card links its Returned figure — real, from the advance ledger — to
a page reading `FinanceReturn`, a table with no writer of any kind. The empty state does
not say "nothing here yet". It says "All corrections resolved. No returned finance items."
So a live returned balance leads, in one click, to a positive assurance that nothing is
outstanding. That page now reads the ledger the figure comes from. Details in §7.

**Four are correct, and should stay as they are.** `ExtraWorkScoringPolicy` is fail-closed
by design: without an approved policy, extra work is tracked but unscored, and the page
says so in a banner. `SchoolGeoPoint` sits at the top of a coordinate fallback chain that
degrades to the school's own lat/lng, then a sub-county centroid, then a district one, and
invents nothing when all four are absent. `StaffTargetProfile` is the legacy annual store
behind `MonthlyPersonalTarget`; targets are set through the performance agreement, and an
absent target renders as "No Target Set" rather than 0%. `RolePriorityTemplate` was
superseded by the priority cascade, which passes `include_role_templates=False` on the
production path. In each case absence is the safe state and the platform says so out loud.

**One is GOV-02, and this report first said four.** The correction is worth making in
full, because the mistake was mine and it is the same mistake this audit keeps finding in
code: I asserted that Compensation & Benefits, Succession Planning and the Maintenance
Calendar were *workspaces a user can navigate to* without checking navigation. Three of
them are not. `apps/core/navigation.py` carries each one commented out with the same line:
"DESCOPED until a production writer exists — the model behind this page has none, so the
page is a permanently empty register. Direct URL still works (honest empty state);
navigation stops advertising it." Payroll Readiness is descoped the same way. Somebody had
already found this, decided it, and written the decision down where I did not look.

That leaves the **Maintenance Calendar**, which genuinely is advertised — linked in the
Admin sidebar and a drilldown target from a dashboard metric — over a table nothing writes.
Its empty state says "No maintenance templates are configured **yet**", the generation job
runs over the empty table, and `admin_ops_stale_maintenance` reports "Maintenance
Generation: ok" permanently. Recurring analytics report schedules are a second-order
version of the same thing and were also decided: the `AnalyticsReportSchedule` model and a
proper `ModelForm` over it exist with no caller, while the drawer a user actually sees
sends an immediate snapshot and says "No scheduler worker or email provider is involved".
Honest, and retired in all but the residue.

What the remaining one has, and what the descoped pages had before somebody dealt with
them, is worth naming: **an empty state that is factually true and inferentially false.**
"No maintenance templates are configured yet" is true. It reads as *nobody has configured
any*, when the fact is *there is no way to configure any*, and the second sentence is the
one an Administrator needs. The word "yet" does more damage than any other word on that
page.

The tempting fix is to rewrite the sentence. This audit did not, and the mandate is why:
*"Do not use cosmetic frontend changes to conceal backend or workflow defects."* Better
copy over an absent capability is precisely that trade — the surface would read more
honestly while the workspace stayed as empty as before. It is recorded for a build-or-
retire decision instead, and the retire option already has three worked examples in this
codebase. FIN-05 was fixed rather than reworded because the data it needed already existed,
in a ledger the figure beside it was already reading; there was a capability to connect,
not one to invent.

**Five are dead ends or descoped surfaces.** `Village` is the leaf of the Ugandan
administrative hierarchy: nothing writes one, the seed stops at Parish, and no template or
script calls `/geography/villages`. `HRAuditEvent` was a second audit table without a hash
chain, already replaced by the canonical log. `CompensationRecord`, `SuccessionCandidate`
and `PayrollReadinessRecord` are the descoped HR registers described above — reachable by
direct URL, honest when empty, and not offered to anybody.

### The scan was wrong twice before it was allowed to say anything

Both errors are recorded because the correction pattern matters more than the result.

The **first** version saw only `Model.objects.create`. It reported
`LoanRepaymentInstallment` as unwritten when `lending_ledger.py` builds one with a bare
constructor. That is the "everything looks broken" failure, and it is the cheaper of the
two — a false alarm gets investigated. All three Python write spellings are now detected:
bare constructor, manager call, related-manager call.

The **second** was the dangerous direction. Django writes rows three ways that are not
Python spellings — a `ModelSerializer.save()`, a `ModelForm.save()`, and the admin site —
and the second pass cleared three suspects on those grounds. Checking those three by hand
cleared only one. `VillageSerializer` is real, but `geography/views.py` only ever renders
with it; a serializer used for output writes nothing. `AnalyticsReportScheduleForm` is a
real ModelForm over a real model and has no caller anywhere in the repository. A form
nobody instantiates writes exactly as much as no form at all.

Then the guard built from all this made the same mistake a third time, against itself: the
first run exempted `AnalyticsReportSchedule` because the guard's own docstring names the
form class, and the usage check was a substring search over every file including that one.
The scan is now blind to test files and to itself.

One deliberate blind spot remains, and it is not a defect. `obj.save()` on a variable is
not counted as a write, because it updates a row that must already exist and so cannot be
what first creates one — which is the only claim this census makes. That rule was
established by an anomaly worth keeping: `AdvanceRequest` shows exactly **one** writing
file, which looked like proof the scan was still broken. It is not. The advance ledger is
saved throughout the codebase and *created* in exactly one place, `advance_service.py`.
The census asserts that, by file, as one of its own control tests.

### The census is a standing guard, not a one-off scan

`apps/core/tests/test_read_only_model_census.py` pins all eighteen models to a literal
dict, each with a written reason describing what a reader of the affected surface actually
sees. A nineteenth read-only model fails the suite until somebody records why. One of the
eighteen gaining a writer also fails it, so a capability that gets built cannot leave a
stale entry behind claiming it was not.

Five control tests hold the scan against models that genuinely use each write form, so it
cannot pass by having gone blind: the bare constructor, the manager call, the related
manager, and three heavily-written models that must never appear in the output. Both
directions were mutation-tested — removing an entry and adding a written model — each
mutation confirmed present in the file before the exit code was read, after three silent
no-op mutations earlier in this audit produced meaningless greens.

### The journey census is now a test, not a sentence

"1 of 22" was a claim with the twenty-two enumerated nowhere and the number checkable by
nobody — the same shape as a skipped test reporting green. The mandate's twenty-two
journeys and their steps now live in `apps/core/tests/release_journeys.py`, each either
pointing at the single test that walks it end to end or saying plainly that nothing does,
and `test_release_journey_census` holds that manifest to reality: a pointer at a test that
does not exist fails by name, and the covered count is pinned so coverage cannot be
claimed or lost without a deliberate edit that the assessment must be updated alongside.
Verified against both drift modes by introducing each and watching it fail.

The census also caught its first error immediately. The one real journey test documented
itself as "Journey 1" while walking Journey 3 — Plan, Cost, Schedule, Fund request,
Approval, Disbursement, Start, Evidence, PL review, IA verification, Accountability,
Closure. Journey 1 is Priority to verified performance, an entirely different spine. A
census built from docstrings would have recorded the wrong journey as covered.

**Twenty of the twenty-two are now walked, one test each, and nothing is unwritten.** The
manifest's rule is that a journey counts as covered only when ONE test walks the whole of
it — "several tests that each verify a step, with the seams between them faked, is exactly
the coverage this platform cannot rely on" — and Journey 10 nearly slipped it: two partial
pointers between them touched every step, and the census would have accepted both, because
it checks that pointers resolve and not what they cover. That was caught and corrected to a
single whole-journey test.

Two cannot be covered by any test at present, and the manifest says so rather than counting
them as merely unwritten:

- **Journey 20, Offline field activity** — FE-01. There is no IndexedDB queue, no replay
  and no server-side idempotency key, so there is no behaviour to walk.
- **Journey 21, Integration outage** — INTG-01. There is no outward transport, so
  "external system fails" and "retry succeeds" have nothing to exercise.

Journeys 15 and 16 were on this list too, blocked on GOV-01, and came off it when the two
registers gained their write path. Both are now walked.

### Journey 8 was walked, and it found a defect on its first run

Journey 8 — Activity cancelled after disbursement — touches three of the mandate's own P0
examples at once: money that has already moved, recovery of what was not spent, and
achievement credit that must not survive the work being called off. The suite tested the
two halves separately and neither knew about the other: the cancellation test disburses no
money, and the money tests cancel nothing. That seam is exactly where FIN-01 (a
cancellation path that CASCADE-deleted a *disbursed* advance) and TGT-02 (cancelled work
keeping its credit) each lived.

Walking the join surfaced **FIN-04** immediately. The advance correctly survives
cancellation, so the financial record persists for audit. The owner can account for what
they actually spent, the Programme Lead can approve it, and the accountant can verify the
returned balance. Then `approve_accountability` refuses: *"Cannot final-clear — IA has not
verified this activity yet."* A cancelled activity never will be — IA verification
certifies work that was **delivered**. So every advance disbursed against work later
called off was stuck at `accountability_pending` permanently: real cash recorded as
outstanding for ever, and an item in the accountant's queue that nobody could clear.

The fix lets called-off work clear, and the control that replaces IA verification is
stronger than the one it replaces rather than weaker: where money is coming back, the
accountant must already have **verified the return** before anything can settle.
Cancelling buys nothing — the achievement credit is reversed on cancellation, the
settlement identity still has to hold, and an over-spend still routes to the reimbursement
pipeline and its own gates. Three tests hold the edges, including one asserting that
ordinary undelivered work *still* requires IA verification, so the new branch cannot have
been written too wide. Verified by reverting: three failures, restored and all pass.

### Journey 7 was walked and found nothing, which is also a result

Journey 7 — Fund overspending and reimbursement — is the platform's only path where money
leaves the organisation a second time for the same activity, which puts it on the
"wrong payment" and "duplicate payment" P0 list. It passed on the first run: a genuine
over-spend routes into the reimbursement pipeline rather than clearing silently, the
payout equals the variance, the second payment is refused, and the settlement identity
holds at the terminal state.

A journey test that passes immediately is worth exactly as much as its ability to fail, so
both of its load-bearing claims were checked by mutation. Making the over-spend clear
silently instead of raising a claim fails it; making `reimburse()` write over
`disbursed_amount` fails it by name. That second one is the non-obvious risk this journey
exists to cover — both fields are "money we sent", and overwriting one with the other
keeps the identity balanced while silently losing what the original disbursement was.

### Journey 5 asks the question a hand-built fixture cannot

Journey 5 — Partner assignment and payment — already had fourteen tests on its payment
half (`test_partner_mou_payments`: the advance/clearance split, the amounts, the duplicate
refusals, the verification gate). Every one of them builds its activity by hand —
`Activity.objects.create(status="scheduled", salesforce_activity_id=...)` with cost lines
written directly. They prove the payment rules *given* a payable activity. They cannot
prove that a real partner assignment ever produces one.

That is precisely where INTG-05 lived: completed and closed partner work carrying no IA
verification was counted verified-and-payable. A fixture that sets the verification field
itself starts downstream of the thing that was wrong, so it could never have caught it.

The journey walks from the assignment instead — handed to a partner at
`pending_scheduling`, self-scheduled, visible on the partner's own plan, executed,
evidenced, IA-verified, then paid — and asserts on the way through that the *unverified*
activity is refused payment. Mutation-checked by removing the clearance gate, which fails
it.

### Journey 1 is the longest, and it is sound

Eleven steps and six owners: an RVP publishes strategy, a role rule decides how each role
carries it, an employee and their manager agree the commitment, a CCEO delivers the visit,
Impact Assessment verifies it, and then My Targets, the performance agreement and the
drill-down behind them are each supposed to say the same thing about the same work. It is
the journey with the most seams, and this audit's consistent finding has been that seams
are where the defects are. This one has none that could be found.

Three things it does well are worth naming, because each is a defect this audit found
elsewhere, designed out here in advance.

`publish` refuses a priority that could never measure — one with no role rules at all ("it
reaches nobody and silently measures nothing"), and one naming a metric the platform does
not compute. The second refusal quotes its own reasoning: an unknown key is not an error
anywhere downstream, `live_progress` falls through every branch and returns zero, "so the
commitment reads as 0% forever and looks like an employee failing rather than a typo".
That is the D5 and GOV-01 failure mode — a capability with no path to a real value —
caught at the moment of publication rather than discovered months later.

The cascade gives a supervising Programme Lead a different metric from the CCEO executing
the work, and records a non-carrying role as an explicit exemption rather than omitting
it, "because an absent row is indistinguishable from an oversight".

And `set_priorities`, which rebuilds an agreement from its payload, refuses a payload that
drops a mandatory commitment or re-points its metric. That write shape — delete and
rebuild from what the client sent — is precisely how a leadership commitment disappears
with nobody deciding to remove it. Both refusals were driven, and the agreement checked
afterwards to confirm neither left it half-rewritten.

**Where the platform and the mandate differ, and why the difference is not a defect.** The
mandate's step 2 reads "IA distributes to PL" and step 3 "PL distributes to self and
CCEO". No such distribution exists, and having read the cascade the omission looks
deliberate rather than missed: a published priority reaches every role that has a rule for
it, resolved by `rules_for_role` at the moment anyone asks. Nobody distributes anything,
which means nobody can forget to. That is stronger than the hand-off the mandate
describes, and this walk tests the mechanism the platform built rather than quietly
substituting it and reporting the journey covered. A journey report that rewrites the
journey is not evidence of anything.

**What the walk asserts at the end** is the join: one verified visit appears exactly once
in the achievement ledger, `live_progress` derives the same figure against the agreed
priority's own denominator, and the percentage is those two numbers rather than a third
computed elsewhere. A companion test drives a scheduled-but-unverified visit through the
same fixture and requires both surfaces to stay at zero — without it, a walk that happened
to count merely-completed work would pass every assertion above and prove nothing about
Impact Assessment at all.

Both halves were mutation-tested. Dropping `IA_VERIFIED_STATUSES` from the `direct_visits`
branch of `live_progress` fails the walk; making the twelve-month phasing round per month
instead of preserving the annual total fails it too. Each mutation was confirmed present
in the file before the exit code was read.

### Journey 10 is two properties wearing seven steps

HR unlocks, Employee evaluates, Manager evaluates, Automatic values stay read-only, HR
oversight, Close, Snapshot lock. Two of those seven are not steps. "Automatic values stay
read-only" and "Snapshot lock" are properties the other five have to hold while they run,
and they are why the journey is on the mandate's list at all. A performance conversation
where the measured figure can be typed over is a conversation about somebody's opinion
wearing a number's clothes; one where the figure moves between the manager writing their
assessment and the employee reading it is a conversation about two different quarters.

Both hold. The design is better than the mandate asks for: opening the window IS the
snapshot, so freezing the numbers is not a separate act anyone could omit — "every agreed
review is frozen at this moment, so the meeting's numbers cannot move while the
conversation is underway". `take_snapshot` refuses to overwrite an existing one, and says
why in four words: "that is the whole point."

The sharpest assertion in the walk is the one where both things are true at once. Real,
IA-verified work lands after HR has opened the quarter. `live_progress` moves, because
verified work is verified work. The snapshot does not, because the conversation is already
underway. A platform that cannot hold both is one where the manager and the employee are
reading different numbers off the same screen.

The read-only property is asserted at the service signatures rather than by trying to
smuggle a value in, because a service that silently ignored an unknown keyword would pass
a string-based probe while a future refactor quietly wired it up. None of the four
conversation writes — reflection, assessment, calibration, acknowledgement — has a
parameter through which a typed figure could reach the computed channel.

The authority rules are driven as refusals, not asserted as a table, and each one is an
inversion somebody could reasonably have got backwards. The employee is the only person
who may write the reflection and the only person who may acknowledge, and is barred from
every assessing action in between. HR governs the window and calibration but may not write
the manager's judgement — a separation the code says it lost once already: "This used to
accept HR as an alternative assessor, so a governance role could write the manager's
judgment on the manager's behalf." And the manager's rating is not the final rating;
calibration decides that, because writing it at assessment time skips the gate.

**A note on what "covered" means, because this journey nearly slipped it.** The first
version of this walk registered two tests against Journey 10 — one carrying steps 1, 4 and
7, another carrying 1, 2, 3, 5 and 6. Between them they touch every step, and the census
would have accepted the pointers, because the census checks that pointers resolve and not
what they cover. The manifest's own rule says otherwise: one test walks the whole thing,
because "several tests that each verify a step, with the seams between them faked, is
exactly the coverage this platform cannot rely on". Two partial pointers dressed as
coverage is the same move as a skipped test reporting green, one level up. The journey now
has a single test that walks all seven steps in order, and the focused ones stay as what
they are — guards on individual rules, claiming nothing.

Mutation-tested at both properties: making `take_snapshot` delete and retake an existing
snapshot fails the walk, and letting `submit_assessment` write the final rating fails it
too. Each mutation was confirmed present in the file before the exit code was read.

### Journey 17 is the strongest subsystem this audit has walked

Eleven steps, six parties and money moving twice in opposite directions. Edify refers, a
microfinance institution lends, a funding facility supplies the principal, Impact &
Analytics verifies what the money did, and district analytics decide where the next
facility goes. None of it is Edify's own budget, which is the reason the ledger governs
as hard as it does.

The governing rule is stated in the refusals rather than in a comment. A loan record
cannot carry a typed disbursement — "Disbursement facts cannot be entered on a loan
record; post a facility-backed disbursement" — and disbursed, active, repaid and
defaulted are refused as *entered* statuses because they are ledger-derived. A repayment
schedule's principal must equal the confirmed net disbursed principal, so a schedule
cannot quietly describe a different loan. A repayment cannot be dated in the future,
because a receipt is a fact about money that has arrived. Each of those was driven here,
and each of them refused.

The separation of duties holds at every seam, and the seams are not where an outsider
would guess. Three different people are needed before a facility can lend: Business
Transformation authors it, the Country Director approves it, and the Accountant confirms
the money actually arrived. Referral belongs to the Country Director alone — it commits
Edify's name and a school's consent to a lender — while the Business Transformation
Officer's authority in this journey is the Salesforce confirmation, recording that the
loan exists rather than deciding that it should. And the party that moved the money does
not certify what it did: the lender reports the use, Impact & Analytics verifies it, and
cannot verify more than was reported. That is this audit's recurring question — can one
party both do the work and sign it off — asked of lending, and answered no at every
layer.

**The eleventh step is the one that could have gone wrong invisibly.** `geographic_equity`
builds a complete district spine, so a district with eligible schools and no lending
reports a zero rather than being absent from the result. Zero and missing are different
findings: one says the programme has not reached a district, the other says nobody knows.
An equity analysis that silently dropped unfinanced districts would report perfect
coverage of wherever it already lends, and would do it while looking entirely healthy.
The walk carries a district that has never borrowed and requires it to be present with
its zero.

Mutation-tested at both ends of that: excluding unfinanced districts from the spine fails
the walk, and counting partner-reported enrolment as verified fails the premise guard
beside it. Each mutation was confirmed present in the file before the exit code was read.

No defect was found. That is worth saying plainly rather than leaving as an absence: of
the seventeen journeys now walked, this is the one whose money moves furthest from
Edify's control, and it is the one whose controls are most explicit about what each party
may assert.

### Journey 6 was the last unwritten one, and walking it found PROJ-01

Ten steps, and unlike every other journey this one does not move work or money. It moves
a claim: at the end of it the platform says a Special Project improved something. So the
rules worth testing are all about what it refuses to claim, and they are unusually good.
A school joins a project because its own confirmed assessment is genuinely weak in one of
the project's declared targets — the service comments say "never fabricate need". The
baseline is snapshotted at the moment of assignment, so the project is judged against the
score it started from rather than whatever the latest reading says. Measurement runs from
a **verified** delivery, never a scheduled one, because "a plan is not an intervention,
and measuring from a date nothing happened on would open the follow-up window early". And
a rate is withheld entirely below a minimum cohort rather than shown with a caveat nobody
reads.

That last rule shapes the end of the walk, and it is worth stating what the test asserts
because a careless version would have asserted the opposite. One school is a real,
measured, improved school **and** too small a cohort to state a project-level rate. Both
are true at once. The walk requires `measured` to be 1, `improved` to be 1,
`average_change` to be the actual gain — and `improvement_rate` to be **None**, with the
limitation string saying why. A test that demanded a percentage there would have been
asking the platform to overclaim.

**And step 10 could not happen at all.** `ssa_impact.refresh_follow_up` is the only code
that writes a follow-up score, a follow-up assessment id, the follow-up due date, or any
classification beyond the two set at assignment. It is complete, careful, explicitly
idempotent and tested — and its only callers in the entire repository were its own tests.
So no project school could ever reach the measured state; `project_impact` reported
"awaiting follow-up" for every project in every financial year, however much verified
work was done and however many follow-up assessments were collected.

The second half is worse than the first. The To-Do that chases a missing follow-up filters
on `follow_up_due_on__lte=today`, and that column is written only by `refresh_follow_up` —
so the reminder that exists to stop this happening could itself never fire.

What made it quiet is that every reader was scrupulously honest. `project_impact` reports
the pipeline stage rather than folding an unmeasured school in as a zero, and withholds a
rate over a cohort too small to mean anything. The To-Do page carries a comment saying an
uncollected assessment "reads forever as 'not yet measurable', which is honest but never
becomes an answer". Nothing lied. The truth was just always the same one — which is the
distinguishing mark of this whole defect class, and the reason it survives green suites.

Two event bridges now reach the refresh, because two different things can make a school
measurable and neither happens in the projects app: a delivery is verified, which opens
the window and fixes the due date, and an assessment is confirmed, which may be the one
that judges the work. Both enqueue onto the durable outbox rather than running inline, for
the same reason the Business Transformation bridge beside them does — a confirmed SSA
arrives one at a time from a verification screen and several hundred at a time from an
import, and the upload path has a query budget a per-row projection would break. The
`outbox_drain` job is registered with the scheduler and covered by INTG-02's alerting.

### The first version of the PROJ-01 test was green for the wrong reason

Worth recording, because the suite would have accepted it. Deleting either bridge left all
five tests passing. The cause is a property of the fix rather than of the test:
`refresh_school_impact` re-derives from current state, so an event enqueued by an *earlier*
step and drained at the end of the test does all the *later* work too. One stale event
covered for a bridge that never fired.

The tests now drain after every step, so each trigger has to carry its own step, and
killing either bridge fails them. This was found only by mutating both — the suite was
green either way, and nothing else would have told me.

That is the fourth distinct way this audit has produced a green that came from not having
looked: a test that skipped itself, a prose claim nobody could check, a mutation that
never landed in the file, and now a fix whose two halves could each hide behind the other.
They have nothing in common except the shape of the result.

### GOV-01 was not a build, and Journeys 15 and 16 came with it

The earlier draft of this report called GOV-01 "a build: the write path was never made",
and listed it beside FE-01 and INTG-01 as work an audit could not close. That was wrong,
and worth correcting rather than quietly fixing, because the reasoning behind it is the
reasoning that leaves defects open.

Both models were fully designed. Statuses, uniqueness constraints, an indexed expiry date,
a complete IA validation lane. Three surfaces read each of them. And — the thing the first
reading missed — **the permission matrix already carried both halves of the workflow**:
`businessTransformation.schoolSupport.manage` on the Country Director, Programme Lead and
CCEO, who are the people who visit a school and see the certificate, and
`businessTransformation.ia.validate` on Impact Assessment alone. A recorder and a separate
verifier, decided before either service existed. Nothing about who does what was an open
question; only the services were missing, in a shape this codebase already uses for the
same problem in `lending_impact.capture_enrolment_snapshot` / `verify_enrolment_snapshot`.

"A build" and "an unimplemented design" look identical from the outside — both are absent
code. The difference is whether the decisions have been made, and the permission matrix is
where this platform records them. Reading it is what turned a blocked finding into a day's
work.

The readers decided the rest. The portfolio counts `compliant` AND `verified` together, so
an unverified assessment is a claim rather than a finding and must not be counted as
compliance. Re-recording a **changed** status withdraws the verification the old status
carried, because a verification of a status that has since changed is not a verification
of the current one — and a no-op re-save must not disturb a standing verification, which
is the converse and is asserted too. And the requirement catalogue's renewal period plus a
registration date are an expiry date, which the register now derives: leaving the reader to
work that out is how a lapsed permit goes unnoticed on a register whose whole job is to
notice.

**The quarantine mechanism worked exactly as designed.** The GOV-01 guard carried
`expectedFailure` rather than `skipTest`, and its own docstring said why: an expected
failure runs, records its failure, and the moment somebody builds the write path reports an
UNEXPECTED SUCCESS that fails the build and forces the marker off. That is what happened.
The read-only model census removed its own two GOV-01 entries the same way — its
stale-entry test fails on a model that has gained a writer, so the list had to be corrected
rather than left flattering. Two guards written earlier in this audit made the fix
impossible to land quietly.

### Journeys 15 and 16, the two that GOV-01 was blocking

They share a spine and diverge at the end, which is why they are walked in one file. A
confirmed SSA weak in Financial Health or in Government Requirements opens a Business
Transformation case and writes the recommendation set for that weakness — automatically,
off the durable outbox, with nobody having to remember. From there Journey 15 measures
whether a school **adopted** a practice it was trained in, and Journey 16 whether a school
**holds** a permit it was helped to obtain. One is behaviour and the other is a document,
and the two registers reflect that difference exactly.

Journey 15's interesting refusal is that training attendance is not practice adoption, and
an assessment recorded by the officer who delivered the training is a claim until Impact
Assessment verifies it. The walk requires the portfolio tiles to keep `assessed` and
`verified` apart at every point, because collapsing them would let the person who did the
work certify their own result.

Journey 16's is the expiry reminder, the step that could most easily have not existed.
`nearest_expiry` is computed per school from **verified** compliance rows only. So a
certificate recorded but not yet confirmed must not appear as a live expiry — a reminder
about a document nobody has seen — and a verified one must. Both are driven, along with an
expired certificate counting as action required rather than as compliance.

Mutation-tested on both: making `nearest_expiry` read unverified rows fails the walk, and
handing a financial-health weakness the compliance recommendation as well fails it. Each
mutation was confirmed present in the file before the exit code was read.

### CORE-01: a critical nobody could clear, on every core school

D5 said `CorePlan.assessment_completed` is unreachable. Walking what the readers do with
that turned a dormant gap into a P1.

`core_assessment_missing` is the **first and most severe** blocker on every core school
row, rendered critical. It is a registered sendable TeamAction whose ask is "Complete the
core assessment" and whose stated reason is that the package cannot be planned until the
assessment is on file. And `condition_still_holds` re-reads `plan.assessment_completed`,
which no core school can ever move: no active catalogue item carries
`core_assessment_visit`, no drawer offers one, and `resolve_item_for_workflow_kind` returns
None.

Put together, the platform told a CCEO to do something, routed them to a page with no
control that does it, and kept the accountability record open for ever. On every core
school. In every financial year.

**What this audit fixed, and what it deliberately did not.** It did not create the
catalogue item. What a Core Assessment costs is a Country Director configuration decision,
and the costing layer says so in as many words — an unknown profile raises "Country
Director configuration must be repaired before scheduling". Inventing a price to make a
test pass would be manufacturing a passing result, which the mandate forbids in terms.

What it fixed is the platform's behaviour while the decision is outstanding. The gap is now
reported in the module that exists to catch exactly this class — whose own docstring says
"If any of these has no active costed catalogue item, ordinary work is blocked again —
which is the entire defect this module exists to catch early" — and it goes green by itself
the moment the item is configured. And the ask is withheld rather than deleted, on the
principle this codebase had already written down a few lines from the registration, about
partner-delivered work: where the responsible actor is somebody else, the ask is not made
of staff, because "manufacturing one against a CCEO for work a partner has not done would
hold the wrong person to it." Work the platform itself blocks is the same case.

**A third test failed, and it was right to.** `test_the_supervisor_can_send_an_action_to_the_responsible_cceo`
is titled for what a Programme Lead "must NOT lose", and the first version of this fix took
it away: refusing the unsendable ask meant a supervisor clicking Send on a core school got
an error instead of an action, because the assessment is the more severe of the two
blockers and the view stopped at the first one. That is a worse trade than the defect —
a silent unresolvable ask replaced by a loud refusal of a capability that should work.

The send now falls through to the next blocker instead of refusing. The package ask IS
resolvable — schedule the outstanding visits and trainings — so the supervisor keeps the
capability, and nobody is handed the ask they cannot close. The test's assertion moved from
`core_assessment_missing` to `core_package_behind` with the reason written into it, and the
service-level refusal stays as the backstop the view no longer reaches. Configure the
catalogue item and the assessment ask becomes sendable again and wins on severity, which
the test also says.

**Two other existing tests failed, and that was the point.** `test_a_clean_platform_is_green`
asserted a seeded platform has no failing scheduling checks. It now has one, because the
platform genuinely ships unable to schedule a mandatory Core slot. The temptation is to
narrow the new check until the old test passes again; what happened instead is that the old
test was corrected to state the truth, with the gap named as an exact set so it is pinned
in both directions — a new failing check has to be looked at, and configuring the item
empties the list and fails the test until somebody removes the entry. A companion test
keeps the original assertion for every other check. The second failure,
`test_a_cancelled_booking_is_history_not_a_fault`, was reading the report's overall
`healthy` flag for a question about agency bookings; it now asserts against the agency
checks it is actually about, which is stronger than the flag it used to read.

## 4b. JRN-01 · The mandated journeys are proven below the door, and two of twenty at it

**P1 · evidence gap · partially closed, 2 of 20 — and the second one found a defect**

The traceability matrix's first finding is about the evidence, and it is one this audit
produced itself, because most of these journey tests were written in this audit.

As the matrix first found it, all twenty walked journeys drove services directly and **not
one issued an HTTP request.** The route column was empty for every row, and that reading
was not the tracer failing to look: a control test proves it records a route when one
happens, and an independent static pass over the twenty journey modules found zero calls to
the test client. Two methods, same answer.

**Journey 19 has since been taken through the door**, and it was the right one to take
first: its entire subject is unauthorized access, so proving it only below the door was the
least defensible instance of the gap. Its covering test now runs a second sweep through the
real endpoints, logged in as each of the thirteen roles, and requires a refusal from every
role that should not hold the act. The two sweeps are kept separate on purpose — the door
and the act are different questions, and the platform answers them at different layers:
the partner-payment route refuses Admin *inside the view* (the FIN-03 check), while the
weekly-disbursement route admits Admin at the door and refuses it in the service. Stating
those separately is what stops the table quietly agreeing with whatever the code happens to
do.

The probe that matters most reproduces SEC-01 at the endpoint SEC-01 lived at. A Programme
Lead who supervises the school's CCEO POSTs to `/schools/<id>/edit-drawer` naming
themselves as the new account owner. They pass the read gate — correctly; that is what
oversight is for — and must be refused the write. **This was verified by mutation:**
deleting `assert_may_write_school` from the view makes the sweep report the takeover with a
200 for the Programme Lead and for Impact Assessment, the two roles that hold
`school_directory` but not ownership. Every other role is stopped at the door. That is the
layered design working, and it is the first time any mandated journey has proven the two
layers meet.

**Journey 7 followed, and it is why this finding was worth raising.** It is the money
path — the platform's only route where funds leave a second time for the same activity —
and its five endpoints reach the guard family journey 19 did not: four DRF views behind
`RequirePermissions` at three different permissions, plus a page view that also runs an
object-level check. Its first run returned a 500 from
`POST /api/fund-requests/advances/<id>/account-approve`, and that is **FIN-06** above: an
endpoint that had never worked, in a codebase with 6,081 passing tests, because nothing had
ever knocked on it.

The denial half of that journey taught something the route sweep needed. This platform
refuses at whichever layer owns the rule, and a status-code-only probe gets it wrong:
`payment.act` is the Accountant's alone, so the CCEO and the PL are stopped **at the door**
with a 403 on both accountant acts — but `budget.approve` is held by the CCEO *and* the PL,
so the CCEO passes the door at `pl-approve` and is stopped **by the service**, which refuses
self-approval. Demanding a 403 there would have reported a working separation of duties as
a security hole. The test asserts the door where the door owns the rule, and asserts *the
money did not move* everywhere — which is the stronger claim in both cases.

**Eighteen of the twenty still do not knock**, so the finding stands and stays open.

The consequence is a seam. This platform declares **810 route-level authority gates** — 526
`require_page_permission` / `require_any_page_permission` decorations and 284 views
carrying `required_permissions` — and until journey 19 was converted, no mandated journey
exercised a single one of them. Four are exercised now.
The permission matrix (§45.5) proves those declarations are coherent: every guarded route
is answered role by role, and none is reachable by nobody. The journeys prove the domain
logic underneath. On four routes, journey 19 now proves the two **meet** — that the view
hands the service the principal it just checked, in the scope it just checked it for. On
the other 806, still nothing does.

That is not a hypothetical seam. SEC-01, the one live privilege escalation this audit
found, lived exactly there: the school edit drawer gated a *write* on the *read* helper.
Both halves were individually correct and individually tested. The defect was the join.

Eight of the twenty go further and consult no authority at all — no permission key, no page
gate, no object-level guard anywhere in the run: journeys 2, 4, 9, 11, 12, 13, 14 and 22
(SSA improvement, cluster training, leave and coverage, professional development, policy
lifecycle, PIP, team oversight, financial-year rollover). This needs stating carefully. It
does **not** mean those workflows are unauthorised. Services also refuse by comparing roles
inline and raising `Forbidden`, at 232 sites, and those refusals carry no permission key
for the tracer to record. What it means is narrower and still uncomfortable: for those
eight domains, the release evidence contains no authorization decision of any kind.

**The same gap has a second half, and it is the more surprising one.** No journey computes
a registered metric either. The twenty runs between them move the source data of **75 of
the platform's 417 registered metrics** — journey 1 alone moves 46 — and not one of them
ever calls a metric's own computing function. So no mandated journey verifies a number a
user is actually shown. They verify the domain state those numbers are derived from, and
leave the derivation to the metric suite to check separately. It is the route gap again in
different clothes: the join between what the platform knows and what it displays is proven
by nothing end to end.

That zero was checked before it was written down. Attribution is function-level, and three
controls prove the join works — the tracer records functions and not merely files, a metric
whose own function ran *is* credited, and a metric whose module ran without it is *not*.
The last one is a regression pin: the first version of this tracer matched on the file and
credited journey 1 with twelve analytics metrics it had never computed. Journey 1's true
count is zero.

**Why this was not visible before.** Each journey test passes, the journey census counts 20
of 22 covered, and every one of those numbers is true. "Covered end to end" was defined as
one test walking the whole journey — which these do — and that definition never said which
layer. This is the same shape as the defect class this audit has been chasing all along: a
capability with scrupulously honest readers and a gap nobody's instrument was pointed at.
It took an instrument that records what ran, rather than what passed, to see it.

**What would close the rest.** The same conversion applied to the remaining nineteen —
logging in as each role, requesting the real URLs, posting the real payloads, and reading
the numbers off the surface the user reads them from — so that the door, the domain and the
display are proven to meet on every high-risk path rather than one. The money journeys (5,
7, 8, 17) are the ones to take next, and journey 17 is the largest prize: eleven
permissions across seven roles, the widest authorization surface in the platform.

It is pinned in both directions meanwhile. `JOURNEYS_THAT_KNOCK` in
`apps/system_health/test_traceability_matrix.py` names the journeys proven at the door, and
`WhichJourneysReachTheDoorTest` fails if that set grows *or* shrinks — the regression and
the improvement both force this section to be rewritten in the same commit, rather than
either going unrecorded. The metric half is pinned separately and is still at zero.

**Why it does not change the verdict.** The release is already **No-Go** on nine
infrastructure gates and three product decisions. JRN-01 does not add a blocker; it
subtracts confidence from evidence already recorded, and this report would be
misrepresenting that evidence if it left the reading at "20 of 22 journeys covered" without
saying which layer those twenty cover.

## 5. Path to a defensible Go

Six items, of which engineering has closed two outright and can close none of the rest
without an environment or a decision.

1. **Product-owner decision on CONFLICT-001.** It is a conflict, not a bug — both fix
   directions break tests encoding the opposite behaviour. Engineering cannot resolve it.
2. **Product-owner decision on CONFLICT-002.** Whether Impact Assessment should author the
   priorities its own verification is measured against. The recommendation, and the reason
   it is a recommendation rather than a patch, are in §8.
3. **Country Director configuration for the Core Assessment.** One catalogue item with a
   costing profile. Until it exists, one of the nine mandatory Core package slots cannot be
   scheduled by anybody; the platform now reports that as a configuration gap instead of
   holding a school to it (CORE-01), and the check goes green by itself once it is
   configured.
4. **Amend the release scope or build the offline client.** The honest options are to
   ship as "installable, online-only PWA" or to build the IndexedDB queue, replay and
   server-side idempotency keys. It is a build, not a patch.
5. **Stand up a production-equivalent staging environment** and run the nine gates
   above, including a real restore and a real rollback rehearsal.
6. **Re-run the full pipeline on the release candidate**, including the container scan.

**Closed by this audit:** the three achievement P1s (TGT-01/02/03) are fixed with
regression tests. And the journeys are walked — twenty of the twenty-two, one test each,
end to end. The earlier version of this list asked the owner to "accept, in writing, which
of them ship unproven"; that request is withdrawn for twenty of them, and stands only for
Journey 20 (offline) and Journey 21 (external transports), which are items 4 and 5 above
under different names.

---

## 6. Workstream findings

### 6.1 Deployment and operations

The single most important finding of the whole audit is that **the repository does not
know what is deployed.**

- **DEP-01 · P0 ·** `.do/app.yaml` carries a "DO NOT APPLY THIS FILE TO THE RUNNING APP"
  banner, and `.do/README.md:17` states the spec "had never been applied since the app was
  created". Worse, the repository's two records of the live application contradict each
  other: `.do/README.md` describes app `edify-planning-app`
  (`dacdc3eb-0ebe-4b47-bea2-88fe1155347b`) with **1** web instance, a **dev-tier** database
  and no Redis; `docs/live-production-audit-2026-08-09.md` describes
  `edify-planning-fra` (`8f8682cd-a00a-42d9-b9a6-4fa4b4140bde`) with **2** web instances,
  managed PostgreSQL 17 + Valkey 8, and a dedicated pre-deploy migration job. Both cannot
  be true, and nothing in a source-only audit can settle it.

  **They are not two descriptions of one app that drifted — they name different UUIDs.** A
  name can be renamed; a UUID cannot. Either the application was recreated between 4 and 9
  August, or one of these documents is not describing production.

  **The two records do not claim equal authority, and this report previously treated them
  as if they did.** `.do/README.md` labels its own topology section "Recorded 2026-08-04
  after the spec repair. *Treat as documentation, not as input*." The live audit is five
  days newer, was taken against the running application, and labels its infrastructure
  table **LIVE PRODUCTION VERIFIED** — a label that document distinguishes deliberately
  from "REPAIRED IN SOURCE" and "NOT VERIFIED", adding that "a passing local test is not
  treated as production evidence."

  That asymmetry changes what DEP-02 means. **If the newer, live-verified record is
  right, production runs two web instances** — and DEP-02 recorded `RUN_MIGRATIONS=true`
  on the web service, so migrations run on container boot. Two instances booting together
  with no advisory lock is the exact configuration `DEPLOY.md` calls unsafe. The advisory
  lock added in this audit was therefore not theoretical hardening; on the more credible
  of the two records it was closing a live exposure. The reassuring single-instance number
  is the one from the document that disclaims itself.

  What this audit could do about it, it did. `apps/core/tests/test_deployment_record_is_singular.py`
  fails the build while the two records disagree, carrying `expectedFailure` so it reports
  an UNEXPECTED SUCCESS — and forces its own removal — the moment somebody reconciles them.
  `.do/README.md` now carries a warning naming the other record, so a reader who opens only
  that file cannot be quietly misled. Five control tests keep the quarantine honest: the
  facts cannot be reconciled by deleting them from one side, and a blockquoted
  cross-reference does not count as agreement. That last rule exists because the first
  version of the guard had no such distinction, and adding the warning to `.do/README.md`
  made the UUID check pass — an unexpected success produced by one document quoting the
  other, which would have read exactly like somebody having resolved DEP-01.
- **DEP-02 · P0 ·** `.do/README.md:87-89` records `RUN_MIGRATIONS=true` on the *web*
  service — migrations run on container boot, making `instance_count: 1` load-bearing.
  There is no advisory lock around migrate (grep for `pg_advisory_lock` finds only two
  unrelated call sites). If the two-instance record is the accurate one, production has
  been running the exact configuration `DEPLOY.md` calls unsafe.
- **DEP-03 · P0 ·** `scripts/backup_restore_rehearsal.sh` is a genuinely rigorous
  round-trip (row-count parity, `django_migrations` parity, unvalidated-FK assertion, app
  smoke). But it defaults to the local database, no CI job invokes it, and every recorded
  run was against the local estate. No backup schedule, retention or PITR setting exists in
  any spec; the database is declared `production: false`; `DEPLOY.md:241` still lists
  "configure an independent backup/export process" as a to-do. **No restore from a
  production backup has ever been performed.**
- **DEP-05/06/07 · P1 ·** Nothing pushes an alert when the scheduler stops
  (`scheduler_health_check` exists and is invoked by no cron, workflow or monitor);
  observability is console logging with **no retention**, no error tracker, and two alert
  rules (`DEPLOYMENT_FAILED`, `DOMAIN_FAILED`); and no document maps the runbooks' roles
  ("Platform owner" ×7) to a named person or contact.
- **DEP-08 · P2 ·** `apps/audit/migrations/0006` widens `subject_id` from `varchar(30)` to
  `varchar(128)` precisely because longer values were being dropped. Reversing it issues
  `ALTER COLUMN TYPE varchar(30)`, which PostgreSQL **errors** on rather than truncating —
  so database rollback past this migration is unavailable for this release.

Credit where due: the runbooks are good operational writing, `scripts/rollback_rehearsal.sh`
asks exactly the right question ("does the previous release run against the current
schema?"), and runbook 7 answers the database-rollback question correctly. The gap is that
none of it has been rehearsed against production or staging for this commit.

### 6.2 External integrations — the largest scope gap

- **INTG-01 · P0 ·** There is **no HTTP transport for Salesforce, NetSuite or the Lending
  Partner feed anywhere in the codebase.** `apps/integrations/services.py:48-60`
  (`push_to_external`) is a single unconditional `raise IntegrationNotConfigured`, and so
  is `validate_external_reference` at `:63-71`. An outbound-HTTP sweep across `apps/` and
  `config/` finds only the SMS and email clients (independently verified).

  **This is a scope disagreement, not a hidden bug, and the distinction matters.** The
  seam is deliberate and documented — "Implementing this against the live APIs is the
  credentialed half of Phase 2c … Until then it refuses loudly rather than pretending."
  The platform is behaving exactly as its authors intended. The release blocker is that
  the mandate makes Salesforce confirmation a *gating* step in several core journeys
  (activity closure, partner-payment eligibility, loan confirmation), and what the
  platform actually gates on is a human-typed string. Either the roadmap item lands or the
  release scope says plainly that Salesforce reconciliation is manual and unverified.

  **What "Confirm Salesforce" does today: a human types a string, it is matched against a
  regex prefix (`TS-`/`SVE-`, or `Loan-<number>`), checked for local uniqueness, and
  stored. Nothing contacts Salesforce.** That locally-typed string is the gate on activity
  closure, IA partner confirmation, core-activity verification and partner-payment
  eligibility.

  The outbox around it is real and well-built — `SELECT … FOR UPDATE SKIP LOCKED` claims,
  crash reclaim counted as an attempt, deterministic backoff, dead-letter with Admin
  notification and a replay command. It simply has nothing to deliver to.
- **INTG-05 · P1 ·** Metric definitions still disagree materially with what the services
  compute. The most serious: **"Partner Payments Pending" folds on
  `("ia_verified","accountant_confirmed","completed","closed")`
  (`apps/planning/partner_oversight_service.py:47,753`) — `completed` and `closed` carry no
  IA verification.** The correct field is computed at `:552` and never read. Unverified
  partner work is presented to finance as verified-and-payable, against a spec that says
  "work Impact Assessment has verified".
- **INTG-04 · P1 ·** 18 registered metrics name a service callable that does not exist
  (3 dead dotted paths). The registry's own `check()` never resolves the path, so its 55
  tests pass while pointing at nothing.
- **INTG-03 · P1 ·** Notification centralisation is not true: six live paths insert
  `Notification` rows directly without a `source_event_type`, and `resolve_condition`
  filters on that field — so those notices **can never auto-close**, persist as permanent
  "Action Required", and are then promoted to urgent by the escalation job.
- **INTG-07 · P2 ·** `AdvanceRequest.accountability_netsuite_id` has no uniqueness
  constraint and no duplicate check; two advances can carry the same NetSuite expense ID.
  `finance_services.py:219-220` declares the rule and does not implement it.

Against that, database-level idempotency is genuinely strong: unique constraints exist on
outbox idempotency keys, activity Salesforce IDs (partial index), MFI loan references,
repayment transactions, partner payments and milestone credits. A replayed webhook cannot
create a duplicate credit, loan or payment.

### 6.3 Achievement and targets

The engine's architecture is sound: planned/phased/planned-output/verified are four
genuinely distinct concepts, credit creation is idempotent behind a
`(rule, activity)` unique constraint, partner work is correctly excluded from staff
achievement (with a non-tautological test), the five performance bands are correct at all
seven boundaries, and the zero-balance rule is enforced server-side in three places
including per-component reconciliation. `refresh_period_targets` is the only writer of
`actual_value` platform-wide; no manual override exists.

Three P1 defects sit inside that sound architecture:

- **TGT-02 · P1 ·** `_cancel_or_defer` (`apps/activities/services.py:~3940`) sets the new
  status and syncs money but never calls `reverse_activity_progress` — unlike the three
  other paths that do (`ia_return`, `ia_services`, `closure_services`). **Cancelling a
  verified activity leaves its achievement credit standing.** No test covered it. A fix is
  in progress in this audit.
- **TGT-01 · P1 ·** `ratio` is a user-selectable measurement type, but only `percentage`
  populates the numeric denominator, and no template anywhere offers a denominator input.
  Rate milestones allocated through the Strategic Priorities page therefore score **0%
  forever** — the guard that produces the repeated `has no denominator` log line is correct
  and deliberate; the defect is upstream, that nothing supplies what it needs.
- **TGT-03 · P1 ·** Annual and quarterly figures for unique-school milestones are summed
  from per-period distinct counts, so **a school reached in two months counts twice** in a
  figure whose name says "unique". Fourteen seeded milestones use these bases.

### 6.4 Frontend, mobile and offline

The design-system layer is strong: the CSS bundle reproduces byte-for-byte from source,
101 contract tests pass, the login page is overflow-free from 320px to 1280px, the token
layer is real and tested, only two raw hex values exist in all templates (both in contexts
where CSS custom properties genuinely do not work), and hover-revealed actions all carry
`focus-visible` fallbacks.

- **FE-01 · P1 ·** **Offline field operation does not exist.** The service worker caches
  only same-origin GETs under `/static/` and deliberately excludes anything
  session-bearing. Offline mutations are not queued — they are *cancelled*:
  `static/js/platform-status.js:82-87` calls `preventDefault()` and announces "This action
  was not sent because you are offline." There is no IndexedDB and no background sync
  anywhere in first-party JavaScript (independently verified). The only offline persistence
  is a `localStorage` draft of seven text fields on one page — no files, no photos. Of the
  four required capabilities (start activity, capture evidence, survive app close, sync
  without duplicates), three are absent and the fourth is partial and text-only.
- **FE-02 · P2 ·** The stated KPI rules are "operational 0–2, dashboard max 4, mobile max
  2". Mobile max 2 is correctly enforced. The dashboard limit is enforced **at 6**, not 4.
  The operational limit is not enforced at all — the inventory deliberately asserts there
  is no per-category limit. `docs/platform-kpi-inventory.json` reports 14 payload groups
  feeding more than six metrics into a six-slot tray that truncates, so metrics are being
  dropped with no UI affordance.

### 6.5 Approved product extensions

Nothing on the approved-extensions list is fully absent — a genuinely strong result across
16 items covering Business Transformation, loans and lending partners, the full HR suite,
Special Projects, SSA impact measurement and the partner workflow. Three are partial:

**A caveat this section owes the reader, raised by the traceability matrix.** The
approved-extensions list exists **only as prose, in this document**. `GAP-01`..`GAP-16`
appear in no machine-readable form anywhere in the repository — three of the sixteen are
named below and the other thirteen are summarised as a count. So "nothing is fully absent
across 16 items" is a claim nobody downstream can check, and it is the last claim of that
shape left in this report. The traceability matrix records it as the one requirement set
it cannot reach, and says why, rather than quietly omitting it: writing the sixteen down is
a product-owner deliverable, and once they are written down they can be traced the same way
the twenty-two journeys now are.

- **GAP-02 ·** IA **cannot** edit Master Priority rows. `_assert_master_author` requires
  Country Director, and IA's RBAC block has neither `STRATEGIC_PRIORITIES_EDIT` nor
  `MILESTONES_DEFINE` — both sit with Admin, the Country Director and the RVP. There is no
  row-level create/edit/delete for priorities or milestones in any UI; the master arrives
  by import or seeding, and after publication cannot be amended at all. This sits at the
  head of the chain the release is meant to prove.

  This entry said "never built" in an earlier draft, and that was the wrong reading. IA
  holds `strategicPriorities.import`, `strategicPriorities.allocate`,
  `strategicPriorities.view`, `milestones.allocate` and `milestones.viewProgress` — a
  precise and deliberate set around the same objects. The exclusion is the design, stated
  in `priority_cascade`: "The RVP and CD author STRATEGY … They never write an individual's
  milestones." Granting the extension as written would let the role that VERIFIES delivered
  work also author what that work is measured against, which is the conflict SEC-03 spent a
  P0 closing one layer down. Now **CONFLICT-002**, with a recommended re-scope: the real
  gap is that an imported master cannot be corrected afterwards, and that wants an
  amendment path, not a wider grant.
- **GAP-15 ·** Offline — see FE-01.
- **GAP-10 ·** "Send School to" builds the non-ownership ask correctly (notification,
  To-Do, audit, idempotent, auto-resolving) but the recipient is never chosen — it resolves
  to the school's existing assignee — and no temporary access grant exists outside a Leave
  record.

### 6.6 Security and access control

Object-level authorization **is** enforced, unconditionally, by purpose-built helpers at
35 call sites — and this was verified empirically, not assumed: the object-level denial
suite (27 tests, 79 subtests) passes while `AUTHZ_MODE` is `shadow`, proving enforcement
is not flag-dependent. Separation of duties holds: Admin is withheld `ia.verify`,
`payment.act` and `budget.approve` by the permission matrix, and two tests POST to the
real endpoints and assert the state did not move. Cross-tenant isolation holds for
partners and lending partners. `bandit` reports no issues across 329,364 lines;
`pip-audit --strict` reports no known vulnerabilities. Production hardening is thorough:
HSTS with preload, secure cookies, `X-Frame-Options: DENY`, a CSP, a 30-minute idle
timeout, weak-secret rejection at boot, and login throttling on both the DRF and HTML
doors. No key material is tracked in the repository.

Against that, one live privilege escalation was found and fixed (SEC-01 above), and one
structural reason it survived:

- **SEC-02 · P2 ·** `RolePermissionService.can_update` and `can_delete` — the functions the
  oversight regression contract tests — have **zero production callers**. The contract
  guards a function nothing calls, and its own docstring claims "the API, the HTMX
  endpoints and the bulk actions all resolve through this one function". They do not.
  That misleading contract is why a green suite coexisted with an open write path.
- **SEC-03 · P2 ·** Field-level encryption at rest is not implemented:
  `ENCRYPTED_FIELDS = ()`. NetSuite identifiers and partner payment metadata are
  plaintext. The posture dashboard is honest about it — it reports `encryptedFieldCount: 0`
  and the flag was deliberately renamed so it could not be misread — so this is a risk to
  accept with a named owner, not an unnoticed hole.
- **SEC-05 · P3 ·** The route/permission scanner covers 536 of 1,028 resolver entries (DRF
  is excluded by design and does carry `permission_classes`), and dedupes by bare function
  name, so a name collision across modules is skipped unchecked. Two collisions exist; all
  four views were verified guarded.

### 6.7 Data integrity

No P0. Every self-audit scanner passes — 190 tests, 1,592 subtests — and the checked-in
inventories were verified **not stale** (regenerated byte-identical to HEAD). No dead
surfaces, no inert controls, no unguarded page routes, no mock data reaching production,
and exactly one client-side business calculation, which is a documented waiver with a
ratchet test and an independent server-side recomputation.

Three of the five invariants the mandate names are protected at the database level —
duplicate Salesforce ID, duplicate MFI loan reference, and one credit per source, all
verified as live indexes in Postgres. Two are not:

- **INT-01 · P1 ·** `fund_requests`, `budget`, `targets` and `partners` declare **zero**
  CheckConstraints. Every amount is a bare `BigIntegerField`, so Postgres accepts a
  negative disbursement. `business_transformation` shows the pattern done properly with 35
  such constraints.
- **INT-02 · P1 ·** `TemporaryCoverageAssignment` and `PartnerAssignment` have no
  constraints at all. "One active assignment" rests entirely on a row lock in one code
  path; any other writer can create a second live assignment. The coverage model's own
  docstring notes that nothing ever writes `expired`, so every assignment reads `active`
  forever.
- **INT-03 · P2 ·** The referential-integrity gate reports clean — against a database with
  zero schools. `docs/verification-ledger-2026-07-21.md` still lists 3,220 orphan school
  references as OPEN, and no repair migration exists. Run the scanner against a production
  restore before the gate is claimed.
- **INT-04 · P2 ·** 45 routed surfaces have no automated test, 29 of them mutating
  `action` routes — including `/ia/verification/<id>/verify` and `/ia/verification/<id>/return`.

### 6.8 Previously documented defects — re-verified at HEAD

The internal audit of 2026-08-16 recorded eight defects. Re-checked against current code
with runtime reproductions: **one is fixed, seven are still present.**

`D1` (an escalated leave request could never be approved) was properly fixed, with a
regression test that passes. Still present: `D2` (P1, the declined-cover access grant),
`D5` (P1, the unreachable core assessment slot), `D8` (P1, impact measurement removing a
school from the champion engine), `D6` and `D7` (P2, package closure and the permanent
health-ratchet false positives), `D3` (P2, silent API leave decisions) and `D4` (P3, a
message claiming a notification that is never sent).

`D2` deserves emphasis. Declining coverage sets `coverage_status = "Declined"` but leaves
`covering_staff` populated; approval then branches on `covering_staff` alone, overwrites
the status back to `"Approved"`, and creates a live `TemporaryCoverageAssignment`. The
decliner receives the absent person's school portfolio, supervisee scope, **approval
authority**, and auto-attribution of their audit actions — while believing they are not
covering, and with the record no longer showing the refusal. One guard in `approve_request`
closes it.

## 7. What was fixed in this audit

Each carries a regression test verified to fail before the fix and pass after.

| Commit | Fix |
| --- | --- |
| `804bd5b` | The partner role-bridge fails closed when its flag is absent |
| `56fa8c6` | The school edit drawer asks the ownership question before it writes |
| `8f8c5b3` | Cancelling or deferring work withdraws its milestone credit |
| `00cdfd8` | The cost-snapshot lock reads the canonical money-moved set, and its test parametrises over that constant so the drift cannot recur |
| `31601f5` | Migrations serialise on an advisory lock instead of on `instance_count: 1` |
| `b2dd49d` | Leave cannot be approved onto a cover who declined it |
| `85b37d6` | Only IA-verified work counts as partner payment pending |
| `202aa78` | Readiness names the degraded dependency it was calling healthy |
| `5d599e3` | An unpayable reimbursement is refused, not discovered after payout |
| `4bdc817` | Partner money movement asks the permission matrix, not a role tuple |
| `6cb508a` | The scheduler pushes what it already knew about its own failures |
| `3e2a096` | The oversight contract answers with the rule writes actually enforce |
| `d996b62` | The metric registry follows the pointer it exists to enforce |
| `697b58f` | A school counts once a year where the basis says unique, not once a month |
| `50493d6` | A rate milestone gets the denominator its own arithmetic requires |
| `e66b3ce` | A leave decision is announced from the transition, not from one of its doors |
| `9964cb8` | A core plan is read by its lifecycle, not by one status in it |
| `d35c85e` | The database refuses the money and assignment states nothing else did |
| `bd33fac` | One notification writer is true, and a scanner guards against the seventh |
| `592ad83` | Every Programme Lead's CCEOs resolve in one read, and the two tests that skipped rather than fail now assert |
| `8f92f44` | The Accountant's Returned figure reaches the money it counts, instead of a table nothing writes |
| `674305c` | Journey 1 walked, and every register with readers and no writers pinned to a machine-checked census |
| `6c2afe6` | Journey 10 walked, and one whole-journey test replaces two partial pointers |
| `d9b1a2c` | Journey 17 walked — the loan, from funding facility to district equity |
| `116b3ec` | A Special Project's impact can become an answer: the refresh is wired to the evidence that should trigger it |
| `3c59aa4` | Journey 6 walked — and nothing on the mandate's list of twenty-two is unwritten |
| `14029e1` | The two school-assessment registers can be written, by the recorder and verifier the permission matrix already named |
| `f09c04d` | Journeys 15 and 16 walked, the two that GOV-01 was blocking |

Supporting commits: `3859103`, `398bd6e` (KPI inventory regeneration), `47b908e` (a test
respelled for a case the new constraint makes impossible), `44f418d` (stale at-risk
notices resolved in one query), and `4aef402`, `120a66a`, `6750c71`, `036982e` (this
report).

A note on method, because it changed an outcome: the first draft of the FIN-01 test
asserted a bare `BadRequest` and **passed against the unfixed code** — `reschedule`
refuses on the scheduling policy long before it reaches the lock. It was only by running
the test against the reverted guard that the tautology showed up. Every regression test
here was checked that way — including the last one, where reverting the batch took the
measurement from 69 back to 112 and the test failed as it should.
## 7a. Deliverable coverage

The mandate asks for twelve deliverables, and **all twelve now exist.** Nine are in this
document: the executive assessment, defect register, journey report, financial
reconciliation, target and performance reconciliation, data-integrity report, security
report, frontend and responsive report, and the deployment and rollback report. The scale
report is here with its result recorded as not established rather than passed. The other
two are generated artefacts held to the live source by tests, described below.

That every deliverable exists is not the same as every gate passing, and this section is
not a victory lap. Two of the twelve carry findings of their own — the permission matrix
invented five before it was corrected, and the traceability matrix produced JRN-01 about
the evidence base itself. The verdict is unchanged and remains **No-Go**.

**The exhaustive permission and scope matrix (§45.5) is now built.**
`docs/platform-permission-matrix.md` and its JSON twin are generated by
`manage.py build_permission_matrix` and held to the live source by
`apps/system_health/test_permission_matrix.py`, the same way the KPI inventory is. It
covers **1,028 routed surfaces**: 845 declare an authority and are answered role by role,
183 declare none and are listed rather than scored, and none is reachable by nobody. The
earlier "536 of 1,028" figure was the old scanner's coverage, not the platform's.

Two things about how it is built matter more than the numbers.

It **asks the real gates rather than modelling them**. Every cell calls
`RolePermissionService.can_view_page` or `has_permission` — the functions the request path
calls — with a stand-in principal carrying only a role, which is all either reads. The
reason is SEC-01: the school edit drawer gated its write on the read helper, and a matrix
assembled from a hand-written copy of the rules would have agreed with the bug. One line is
mirrored rather than called (the any-of semantics of `RequirePermissions`), and a test
drives that line through the real permission class so the mirror cannot drift.

That test exists because the first version got that line wrong. It used all-of where the
guard is any-of, and immediately reported five API routes as reachable by no role at all —
a finding it had invented. The corrected matrix reports zero. This is the fourth time in
this audit that a tool built to find defects produced one of its own, and the only reason
each was caught is that every result was checked against the thing it claimed to describe
before it was written down.

It also **counts what it cannot answer**. The 183 surfaces declaring no authority are
listed by route and view rather than dropped: 74 are Django admin, which carries its own
authentication, 14 are generic redirects, and 9 are the login and MFA views that must be
open. The remainder — document viewer and download routes, messaging, notifications,
geography lookups — may well be guarded inside the view body, and this module cannot tell.
It says so instead of scoring them, because a coverage percentage that quietly excludes
what it could not classify is the problem the old figure had.

**The requirements traceability matrix (§11, §45.2) is now built too**, and it is the last
of the twelve. Two prior audits deferred it, including the internal audit of 2026-08-16,
and the reason is not hard to see: written by hand it is a spreadsheet of assertions, and a
spreadsheet of assertions is the same evidence problem this audit has spent its time
closing everywhere else. Nobody can check it, and it is wrong the first time a service is
renamed.

So `docs/platform-traceability-matrix.md` asserts nothing. For each of the twenty-two
mandated journeys it **runs that journey's own covering test with the platform
instrumented** and records what was genuinely touched: the HTTP routes requested, the
first-party source files executed, the models written, the permissions and page gates
consulted, the notifications raised, the audit actions written, and the metrics the run
computes and moves. Roles come from the RBAC tables — the roles that hold the permissions
the run actually checked. Every cell is a record of an execution, not a claim about one.
Twenty requirements are traced this way; the two blocked journeys get a row carrying the
reason and no trace at all, because there is nothing to run.

Three things about it are worth stating.

It **had to be launched as a test run to mean anything.** `config/settings/base.py` decides
`IS_TESTING` from `sys.argv` at import time, and with it fiscal-year rollover,
platform-failure detection, interaction telemetry and the blocking-IO guard. Launched as an
ordinary management command the tracer loaded the *production* configuration, post-migrate
seeding took a different branch, and the policy-lifecycle journey failed inside the tracer
while passing in the suite — seeding had published two extra mandatory policies whose
audience then owed acknowledgements. The command now re-executes itself once with `test` in
argv rather than trace a platform the suite has never proved. That is a real property of
this codebase worth knowing: any tool that runs the suite from outside `manage.py test`
gets a different platform.

It **is held by controls, not by trust.** A tracer that records nothing produces a matrix
full of honest-looking zeroes, and a zero reads exactly like "the platform does not do
this". `apps/system_health/test_traceability_matrix.py` therefore runs the tracer against
known-answer fixtures — one that makes an HTTP request, one that writes a model, one that
checks a permission, one that fails on purpose — and asserts it saw each, that it refuses to
record evidence from a red test, and that it never appears in its own results.

And it **found its own defects twice before it was allowed to say anything**, which is now
the fifth, sixth and seventh time in this audit. Its first version attributed metrics by module
file, and credited one journey with twelve analytics metrics because an unrelated function
in the same file had run; attribution is function-level now, and that journey's true count
is zero. Its service-path resolver walked a dotted path down until something existed, which
for any unresolvable path was `apps/__init__.py` — so a metric pointing at a deleted module
would have looked perfectly traceable. And its static second-method check for JRN-01
matched `self.client.get(` and the other four verbs, which journey 19's route sweep walked
straight past — it dispatches with `getattr(self.client, method)` so one table can drive
GETs and POSTs alike — so the check reported that journey as not knocking while the matrix,
which records what actually ran, reported four routes. All three were caught by checking
the output against the thing it claimed to describe, and all three are now pinned by tests.

The third is the one worth dwelling on, because it is the argument for keeping two methods
rather than one. The static check exists precisely so a converted journey and a stale
artefact cannot quietly agree — and it only earned that keep by *disagreeing* with the
matrix and losing. A narrower pattern would have agreed with the artefact by accident and
gone on looking like corroboration.

One more thing was fixed before the artefact was committed: recorded routes carried raw
fixture CUIDs, so two builds of an unchanged platform produced different files. Identifiers
are normalised to `{id}` now, with controls in both directions — opaque ids replaced, real
route words kept, since collapsing two distinct routes into one would overstate door
coverage. Two independent full builds are byte-identical, which was checked rather than
assumed.

What the matrix found is **JRN-01**, in §4b — and it is about this report's own
evidence base rather than about the platform.

## 8. Release Requirements Conflict Register

## CONFLICT-001 · Leadership and the Programme Lead read different achievement percentages for the same team

| Field | Value |
| --- | --- |
| Conflict ID | CONFLICT-001 |
| Requirement source A | `CDAnalyticsService._weighted_achievement()` — weights against `active_target_areas()`, the whole `TargetArea` catalogue (`cd_analytics_service.py`, `areas = areas or active_target_areas()`) |
| Requirement source B | `PLTeamTargetsService.get_page()` — derives areas per user from the agreed annual performance review, and renders "No measurable team priorities agreed" when there are none |
| Current system behaviour | For a team with **no signed agreements**, the Country Director's dashboard pools 2 achieved over 1 target and reports **200%**, while that team's Programme Lead correctly sees "Not Assigned" and **0%** |
| Affected roles | Country Director, Regional Vice President (consumers of the inflated figure); Programme Lead, CCEO (the work being miscounted) |
| Affected workflow | Achievement → Performance → Leadership Decisions |
| Financial/data risk | Leadership reads a fabricated achievement figure. The mandate forbids exactly this: "No number may be fabricated", "Pages to calculate different values", "Leadership receives truthful, actionable intelligence" |
| Product-owner decision | **REQUIRED — NOT YET MADE** |
| Resolution | Blocked on the decision below |
| Test proving the resolution | `apps/analytics/test_target_formula_unification.py:214` `test_cd_pl_target_percentage_matches_pl_team_targets` — currently marked `@unittest.expectedFailure` |

### Why this is a conflict and not a bug to patch

The codebase states plainly that both fix directions were attempted and reverted,
because each breaks tests that deliberately encode the opposite behaviour:

- **PL falls back to the catalogue** → breaks 3 tests, including
  `test_global_target_catalogue_does_not_invent_team_priority_rows`, which pins the
  honest empty state and the no-fabricated-data rule.
- **CD adopts priority areas** → breaks 6 tests, including the four
  `test_target_percentage_consistent_q*` cases, whose fixtures assume catalogue-based
  CD maths.

The test's own docstring draws the conclusion: *"Choosing between them changes what
leadership reads off a dashboard, so it is a product decision rather than a patch."*

### Assessment

The engineering handling of this is exemplary — the defect is reproduced by a real
test, quarantined rather than deleted, documented with both attempted fixes, and the
marker is self-removing (unittest fails the run on an unexpected success, so whoever
fixes it is told to remove the marker).

But quarantine is not resolution. **This is an open P1 defect that the release cannot
carry**, because the surface it corrupts is the one the mandate names as the platform's
purpose: leadership receiving truthful intelligence. It requires the product owner to
decide which denominator is authoritative, before the release, not after.

**Recommended decision** (for the owner, not for engineering to take): source B is the
honest one. A target nobody assigned should not have work counted against it; the PL's
"Not Assigned" is the truthful state. That implies CD analytics should adopt the agreed
priority areas and the six catalogue-based CD fixtures should be re-based — a change
with a known, bounded test cost.

## CONFLICT-002 · An approved extension asks Impact Assessment to author what it is meant to verify

| Field | Value |
| --- | --- |
| Conflict ID | CONFLICT-002 |
| Requirement source A | Approved product extension GAP-02: Impact Assessment can edit Master Priority rows |
| Requirement source B | The RBAC matrix and the priority cascade. `strategicPriorities.edit` and `milestones.define` are held by Admin, Country Director and Regional Vice President — **not** Impact Assessment. `apps/hr/priority_cascade.py` states the rule in its own words: "The RVP and CD author STRATEGY … They never write an individual's milestones" |
| Current system behaviour | IA holds `strategicPriorities.import`, `strategicPriorities.allocate`, `strategicPriorities.view`, `milestones.allocate` and `milestones.viewProgress` — it may bring the master in, hand priorities and milestones to people, and watch progress. It may not author or amend the strategy, or define the measurement |
| Affected roles | Impact Assessment (the authority in question); Country Director and RVP (the authors today) |
| Affected workflow | Strategic priority → cascade → agreement → My Targets → verified performance |
| Financial/data risk | Not financial. The risk runs the other way: Impact Assessment is the role that VERIFIES delivered work, and `Permission.IA_VERIFY` sits in `ADMIN_EXCLUDED_PERMISSIONS` precisely so no account both certifies work and releases money for it. Letting the verifier author the priorities their verification is measured against is the same class of conflict, one layer up |
| Product-owner decision | **MADE, 2026-08-26: granted.** Impact Assessment may edit Master Priority rows |
| Resolution | **Implemented.** IA holds `strategicPriorities.edit` and `milestones.define`; `confirm_milestone` reads `milestones.define` at the act; publication stays the Country Director's |
| Test proving the resolution | `apps/hr/test_target_distribution.py::MasterGovernanceTests` — IA confirms and cannot publish, a role with neither permission is refused at both the service and the door, and the audit row names the actor. Mutation-verified in both directions |

### Why this is a conflict and not an unbuilt feature

The earlier draft of this report recorded GAP-02 as "an approved extension that was never
built", which is the reading that leaves it open for ever. It is not unbuilt. The platform
built the **opposite**, deliberately, with the authority split written down in the module
that depends on it, and IA given a precise and different set of powers around the same
objects: import, allocate, view.

That distinction matters to whoever decides. "Never built" invites someone to build it.
What is actually being asked is whether to remove an authorship separation the cascade is
designed around — and the argument against comes from this platform's own security
reasoning. SEC-03, found earlier in this audit, was a P0 precisely because `certify_activity`
let any role stamp work IA-verified; the fix reads `Permission.IA_VERIFY` from the matrix,
which withholds it from Admin so that no single account can both verify work and release
the money for it. An IA that authors the strategic priority, allocates it, and then verifies
the work claimed against it holds all three positions in that chain.

### Assessment

Low severity for the release — nothing is broken, no number is wrong, and no user is
blocked from work they are entitled to do. But it should not be carried as a to-do list
item, because implementing it as written would weaken a separation this audit spent a P0
establishing.

**Decided by the product owner on 2026-08-26: granted.** The stated reason is that Impact
Assessment works *with* the Country Director to assign priorities and is the role that
monitors everyone's progress against them — and IA already imports the master, so being
unable to correct what it brought in was the practical complaint. This audit argued the
other way and was overruled; the argument is kept below because a reader deserves to see
what was weighed, not because the decision is in doubt.

**What was actually built, and what deliberately was not.** IA now holds
`strategicPriorities.edit` and `milestones.define`. Confirming a source figure reads
`milestones.define` from the permission matrix at the act — SEC-03's lesson, since two roles
now hold it and a hard-coded role comparison would be a second place to keep in step.
Publication did **not** move: `_assert_master_author` still restricts it to the Country
Director, IA does not hold `strategicPriorities.approve`, and a test fails if publication is
ever widened to editors. Working with somebody is not signing on their behalf.

**One thing nearly shipped broken, and it is the reason JRN-01 matters.** The view carried
its own copy of the rule — `if not _is_cd(request)` — so granting the permission and opening
the service would have left IA refused at the door while the act allowed them. Every
service-level test would have passed. The duplicate is gone (the `publish_master` branch
beside it never had one and trusts its service), and a test now drives the real endpoint as
IA. Restoring the duplicate turns it red.

**The original recommendation, for the record** (not taken): keep the split and re-scope. If the underlying need is that a master priority cannot
be corrected after import — which is true today, and the more likely real complaint — the
answer is an amendment path owned by the Country Director, with IA able to propose. That
is the shape the platform already uses for loan purposes: `purpose.request` on the partner,
`purpose.review` on the BT Officer, `purpose.define` on IA, `purpose.approve` on the CD.
Four roles, one object, nobody holding two ends of it.
