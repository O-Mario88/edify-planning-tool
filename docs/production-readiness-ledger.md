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

## 6. Pass 2

1. ISSUE-001 and ISSUE-002 — move SSA verification and finance transitions into
   their canonical services, with regression tests that fail if a view writes
   the field again.
2. ISSUE-005 — move the weighted SSA mean server-side.
3. ISSUE-004 — triage the remaining raw mutations.
4. ISSUE-006 — declare or formally except.
5. Build the planning-time instrumentation harness so the human baseline can be
   collected.
