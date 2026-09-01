# Release readiness audit — 2026-08-29

**Verdict: NO-GO.**

| | |
| --- | --- |
| Release candidate audited | `b5b1741c1d8193a326aed079568cb6c2f08bd8f7` (= `origin/main` at audit start) |
| Base moved mid-audit | `main` advanced four times while this audit was open — `e2a0b64c` (PR #80, which removed the scheduling governance behind CONFLICT-004), `f79918f8` (PR #81), then `f5999e00` (PR #82). The audit's fixes were carried onto `main` by those routes, so what this branch still adds is CONFLICT-004 alone. **Every figure below is true of the commit it names and no later one** — that is the cost of auditing a branch that keeps moving. |
| Audit branch | `claude/edify-production-readiness-audit-xgl7jx` |
| Environment | PostgreSQL 16, Redis 7, Python 3.13, live checkout |
| Final local suite | 6,228 tests, `OK`, at `68ed46c25a379edc9f5dc7c7241bb6c8390e8e65` |
| CI on the audit head | all six checks green at `2248cdf5` — see §5a |

Every claim below is either a command whose output is quoted, or is marked
**Not Tested**. Not Tested is not Green. Where a prior audit's finding is
repeated here it was re-verified today, not copied.

---

## 1. Blockers

### B-1 · Every organisation-wide document was readable without logging in · P0 · fixed here

`audience_matches()` is the canonical audience authority. "Everyone" is written as
a present audience rule with no field set, and every per-field check in that
function is a `continue` on mismatch — so a rule constraining nothing fell through
to `return True` for whoever asked, including `AnonymousUser`. The document routes
are audience-gated rather than role-gated by design, carry no
`@require_page_permission`, and no middleware requires a session.

Proven by request, not by reading:

```
[probe]  audience_matches(doc, AnonymousUser) = True
[probe]  ANON GET /documents/probe-safeguarding/          -> 200
[probe2] ANON GET /documents/probe-confidential/download  -> 200
[probe2] BODY RETRIEVED ANONYMOUSLY: b'CONFIDENTIAL-DOCUMENT-BODY'
```

This is the real production data shape, not a contrived one. On a freshly migrated
(non-test) database:

```
          slug            |  status   | role | country | user_id | partner_id
--------------------------+-----------+------+---------+---------+-----------
 edify-safeguarding-policy | effective |      |         |         |
 edify-apostles-creed      | effective |      |         |         |
```

Both seeded by `documents.0002_seed_first_login_agreements`, both `effective`
(a readable status), both carrying an all-empty audience rule. That migration
returns early when `settings.IS_TESTING`, so **no test database ever held the shape
that would have shown it** — which is why 6,216 passing tests ran straight over it.

Fixed in the one predicate rather than at the four routes: `_readable_or_404`, the
engagement heartbeat, `readable_documents`, `targeted_users`, the Upload Center and
the policy gate all ask it, and six copies of an authorisation rule are six things
that drift.

After the fix, against that same real database over HTTP:

```
ANON GET /documents/edify-safeguarding-policy/          -> 404
ANON GET /documents/edify-apostles-creed/               -> 404
ANON GET /documents/edify-safeguarding-policy/download  -> 404
ANON GET /api/health/live                               -> 200   (server genuinely serving)
```

And the fix is scoped, not blunt — the onboarding flow the browser suite depends on
still works:

```
cd@edify.org          sees: ['edify-safeguarding-policy', 'edify-apostles-creed']
ia@edify.org          sees: ['edify-safeguarding-policy', 'edify-apostles-creed']
AUTHENTICATED GET /documents/edify-safeguarding-policy/ -> 200
```

Five regression tests for SEC-A1 itself, each proven to fail without the fix (two more in the same file cover SEC-A2 and SEC-A3).

### B-2 · The full suite was red on `main` · P1 · fixed here

The mandate makes a failed regression suite a stop-the-line blocker. It was failing,
and had been failing on roughly three days of every month without anyone noticing,
because it goes green again on the 1st.

`apps/activities/test_cancelled_work_is_never_achieved.py` built its
`MilestonePeriodTarget` window as first-of-month + 27 days — ending on the 28th —
while dating the activity `today`. On the 29th, 30th and 31st the activity fell
outside its own period, the credit engine correctly declined to count it, and the
fixture's own anti-tautology guard failed:

```
AssertionError: Decimal('0.00') != 1 : the verified activity did not move the
period actual, so the reversal assertions below would hold for the wrong reason
```

Today is the 29th. Fixed to the real month end, with a property test over every
day of five months including a leap February.

### B-3 · "Confirm Salesforce" does not contact Salesforce · product-owner decision · OPEN

Re-verified today: `push_to_external` is a single unconditional
`raise IntegrationNotConfigured`, and there is no HTTP transport for Salesforce,
NetSuite or the Lending Partner feed anywhere in the codebase.

A human types a string; it is regex-checked for a prefix and for local uniqueness,
and stored. That locally-typed string gates **activity closure, IA partner
confirmation, core-activity verification and partner-payment eligibility** — money
and verification.

The platform behaves as its authors intended and documents the seam. The blocker is
that the mandate treats Salesforce confirmation as a *verified* gate, and what gates
is a typed reference. Shippable the moment someone writes down which of those is true.

### B-4 · Offline field operation does not exist · product-owner decision · OPEN

Re-verified today: no IndexedDB and no background sync anywhere in first-party
JavaScript. Offline actions are not queued, they are cancelled —
`platform-status.js` calls `preventDefault()` and announces "This action was not
sent because you are offline."

Mandate §33 and Journey 20 require offline start, evidence capture, survival across
app close, and sync without duplicates. **Journey 20 cannot pass**, and §40's gate
"Offline critical workflows pass" cannot be ticked.

---

## 2. Defect register — fixed in this branch

| ID | Sev | Finding | Fix layer | Test |
| --- | --- | --- | --- | --- |
| SEC-A1 | P0 | Unauthenticated read, and file download, of any organisation-wide document | `audience_matches()` — the canonical audience authority | `apps/documents/test_anonymous_audience_access.py` (7, covering SEC-A1/A2/A3) |
| SEC-A4 | P1 | Admin held `milestones.define`: the technical super-role could edit a country target's figure, Core/Client split, participants guidance and allocation method | `ADMIN_EXCLUDED_PERMISSIONS` | `apps/hr/test_master_priority_editor_authority.py` (4) |
| TGT-02 | P1 | Suite red on the 29th–31st of every month | test fixture window | property test over 5 months incl. leap day |
| SEC-A2 | P2 | Superseded acknowledgement deep link answered 500 | `submit_acknowledgement_view` / `attest_offline_view` | `StaleDeepLinksAndSignedOutLandingTest` |
| SEC-A3 | P3 | `/policy-agreement/restricted` answered 200 to signed-out callers | `restricted_view` | same |
| SEC-A5 | coverage | Cross-MFI loan isolation was correct but unpinned — no test built a second tenant | test only, no behaviour change | `apps/business_transformation/test_mfi_tenancy_isolation.py` (3) |

SEC-A4 was proven against the guard rather than inferred:

```
[probe] CountryDirector        edit-source-figure=ADMITTED  publish=ADMITTED
[probe] ImpactAssessment       edit-source-figure=ADMITTED  publish=refused
[probe] RegionalVicePresident  edit-source-figure=ADMITTED  publish=refused
[probe] Admin                  edit-source-figure=ADMITTED  publish=refused
[probe] Program Lead           edit-source-figure=refused   publish=refused
[probe] CCEO                   edit-source-figure=refused   publish=refused
```

## 3. Found, deliberately not fixed

| ID | Finding | Why not |
| --- | --- | --- |
| CONFLICT-004 | **The release candidate moved during the audit, and the scheduling governance the mandate requires was deliberately removed.** `main` commit `23e3bfba` (2026-08-31, owner-authored) states it plainly: scheduling visits, trainings and cluster meetings "no longer requires recommendation override reasons, applicable SSAs, calendar-policy dates (Sundays/holidays/blackouts/leave), catalogue eligibility/delivery approvals, frequency caps, or client/partner annual entitlements." Structural validation — targets, dates, duplicates, cost rates — remains. Verified rather than inferred: `apps/activities/services.py` now imports only the identity helpers from `apps.core.calendar_policy`, not `SchedulingPolicyService`; and the follow-up commit rewrote the contract tests to assert the opposite, `test_a_project_required_activity_still_refuses_without_one` ("Relaxing the default must not remove the real rule") becoming `test_catalogue_project_flag_does_not_block_scheduling`. | This is a product decision, clearly made and clearly described, so it is registered rather than reverted. But it is a decision **against** requirements this mandate states: §20.2 requires scheduling to govern Sundays, Saturdays, public holidays, leave, organisation events, blackouts, conflicts and five-activity warnings, and says "the same scheduling-policy service must govern creation and rescheduling"; Journey 9 requires leave to produce a calendar block. Those gates cannot now pass as written. Either the mandate's scheduling section is superseded, or this change is, and only the product owner can say which. |
| CONFLICT-003 | RVP also holds `milestones.define`. Mandate §18.1 says "RVP and Admin remain read-only for business values"; `apps/hr/priority_cascade.py` has the RVP authoring strategy. Two sources genuinely disagree. | §3 requires a conflict be registered and decided by the product owner, not resolved silently inside an audit fix. The Admin half had three sources agreeing and was fixed. |
| OBS-1 | `Permission.STRATEGIC_PRIORITIES_EDIT` is granted to four roles and checked nowhere — it appears only in `rbac.py`. The real gate is `milestones.define`. | Gates nothing today. Latent: adding one decorator would hand RVP and Admin an authority nobody re-reviewed. Removing it deletes the scaffold for an approved extension (§4). Needs a decision, not a patch. |
| OBS-3 | The mandate requires dashboard cards to equal their drill-down totals (§28). Target percentages are pinned hard — `test_target_formula_unification.py` reconciles the CD and PL surfaces with 1,000-case property tests — but `/analytics/drilldown` is covered for *rendering* correctness, not for numeric agreement with the card that links to it. | A general card↔drill-down reconciliation harness is a piece of work, not a patch: it needs a card-to-query mapping that does not exist yet. Recorded rather than half-built. |
| OBS-2 | `permission_matrix` recognises only `page_permission` / `required_permissions`, so it reports 21 routes as "unguarded" that are in fact guarded by `_permission`, `_catalogue_permission`, `_require_permission`, `_manual_activity_permission` and `_require_export`. | **This is how SEC-A1 hid** — four genuinely open routes sat undistinguished among 184 false positives. The fix is small (have those five decorators also set `required_permissions`, the contract the matrix already reads) but it changes four checked-in artifacts, so under the §5 scope freeze it is recommended as the first post-release change rather than folded in here. |

---

## 4. Gates run

| Gate | Command | Result |
| --- | --- | --- |
| Python lint | `ruff check .` | **PASS** |
| Python format | `ruff format --check .` | **PASS** — 1,579 files |
| Migration consistency | `makemigrations --check --dry-run` | **PASS** — no changes detected |
| Migrations on a fresh database | `migrate --noinput` | **PASS** — 326 migrations across 44 apps applied cleanly |
| Full Django suite | `manage.py test --parallel 4` | **PASS** — 6,228 tests, `OK`, at `68ed46c2` |
| Static security | `bandit -r apps config -ll -ii` | **PASS** — 0 findings |
| Dependency CVEs | `pip-audit --strict` | **PASS** — no known vulnerabilities |
| JS dependencies | `npm audit --audit-level=high` | **PASS** — 0 vulnerabilities |
| CSS clean diff | `npm run build:css` + `git diff --exit-code` | **PASS** — bundle matches source |
| Workflow supply chain | `zizmor --offline --persona=regular .github/` | **PASS** — no findings |
| Production settings | `check --deploy` under `config.settings.prod` | **PASS** — 0 issues |
| Production boot guard | same, secrets removed | **PASS** — refuses to boot, and says why |
| Environment stamp (§12.1) | `EnvironmentStamp` / `demoDataOnProduction` | **PASS** — demo-seeded database is stamped; a production stamp plus demo data raises a critical blocker |
| Data-integrity checks (§31) | `apps.system_health.services.report()` on the seeded database | **PASS** on the money and verification families |

Four full runs, on the same machine, in order:

| Run | Commit state | Result |
| --- | --- | --- |
| 1 | `b5b1741` — the release candidate as found | **FAILED** (3) — two TGT-02 credit-reversal failures, one stale inventory |
| 2 | SEC-A1 + TGT-02 fixed | **FAILED** (2) — both inventory staleness, one a race with my own concurrent edit |
| 3 | inventories rebuilt, SEC-A4 added | **FAILED** (1) — the Admin boundary contract, correctly refusing an unrecorded change |
| 4 | `68ed46c2` — provenance recorded in the contract | **OK** — 6,228 tests |

Run 1 is the number that matters for the verdict: the release candidate's own
suite did not pass on the day it was to ship.

The boot guard is worth naming. With real config absent, production refuses to start
and names each reason: secret length, `AUTHZ_MODE must be "enforce"` (object-level
authorization cannot run in shadow), object-storage credentials, super-admin
password, field-encryption key. Misconfigured production cannot come up.

On §31, these all returned zero on a 700-school, 260-activity, 1,006-SSA seeded
database: `duplicatePartnerPayments`, `partnerPaidWithoutPayment`,
`salesforceCompleteNotInIaQueue`, `iaClearedMissingFinance`,
`overspendMissingReimbursement`, `financeClearedNotClosed`,
`annualBudgetReconciliationBreaks`.

## 5. Gates not run

| Gate | Why |
| --- | --- |
| Production smoke test | No production access. |
| Restore from a production backup | No managed database. Never performed (prior audit A-3). |
| Rollback and deployment rehearsal | No deploy target. |
| Monitoring, alert delivery, named incident owner | Organisational. |
| 50,000-school scale | The repo's own gate measures 15,000; full scale needs production-equivalent hardware. |
| Physical device matrix | No devices. CI covers *emulated* Chromium, Firefox and WebKit desktop plus android-360, iphone-390 and tablet-768; a real handset on a real network is a different test, and the mandate asks for that one. |
| Real integration sandboxes | None exist to point at — see B-3. |

Seven of the mandate's §40 gates sit in this table. None can be called Green.

**Two gates moved out of this table after the audit closed** — see §5a. They were
listed here because this environment has no Docker daemon and no browser run was
performed locally; CI on the audit head ran both.

### 5a. Closed by CI on the audit head

CI ran the two gates this environment could not, on head `2248cdf5`, and both
passed. All six checks are green.

| Gate | Job | Result |
| --- | --- | --- |
| Container build, non-root check, runtime import, **Trivy CRITICAL/HIGH scan** | Security Scans | **PASS** (2m49s) |
| Browser journeys and the authenticated role route audit | Browser Journeys & Role Route Audit | **PASS** (14m36s) |
| Full suite, lint, format, migration check, CSS clean diff | Django Lint & Test Suite | **PASS** (21m49s) |
| Static analysis | CodeQL, Analyze python, Analyze javascript-typescript | **PASS** |

Two caveats, so neither result is read as more than it is:

- The Trivy step is configured `ignore-unfixed: true`. What its pass proves is that
  **no *fixable* CRITICAL or HIGH vulnerability remains in the runtime image** — which
  is the repo's own gate, and is sufficient to stop treating **CVE-2026-14456**
  (OpenSSL QUIC DoS, HIGH, prior audit A-1) as an open blocker. It is not proof that
  the CVE is absent, only that nothing fixable is outstanding.
- The browser suite is 120 tests over four files and six projects — Chromium,
  Firefox and WebKit desktop, android-360, iphone-390, tablet-768 — and covers an
  authenticated route audit for fourteen roles, three freeze-regression checks, a
  public smoke (login accessibility, and health endpoints distinguishing process
  from dependency state) and a 50-navigation soak. It opens **argument-free pages
  only**. It does not exercise forms, workflow-state-specific actions or exports, so
  it does not close the mandate's journey gates.

### 5b. Second pass — 2026-08-30

Four domains the first pass left as Not Tested were probed against a live
database, with real HTTP requests rather than by reading the scoping code.

| Probe | Result |
| --- | --- |
| Cross-MFI loan isolation | **PASS.** Two tenants built: MFI A's admin sees only A's book, MFI B's only B's. A loan officer sees the records they registered, not the tenant portfolio. CCEO, Program Lead and **Admin** all 403; Country Director reads programme-wide. |
| Cross-partner isolation | **PASS.** With `PARTNER_ROLE_BRIDGE` off (the production shape), two linked partners each resolve to their own organisation and `/partner/schools` shows only their own school. |
| `PARTNER_ROLE_BRIDGE` fallback | **Defended.** The unlinked-user fallback pins to "the first active partner", which would be a cross-tenant grant — but it defaults off, `prod.py` both raises on a truthy value and hard-sets `False`, the DO manifests pin it, and `test_partner_bridge_fails_closed.py` pins the direction. Its docstring records that the default was once `True` and was corrected. |
| Money moving exactly once | **PASS, already covered.** `test_concurrent_money_movement.py` releases genuine threads against PostgreSQL on a barrier and asserts one disbursement, one reimbursement, one partner payment, one audit row, and the settlement identity after the full loop. |

One coverage gap was found and closed (**SEC-A5**): the loan API's role list was
well tested, but no test built a *second* MFI, so nothing would have failed if
`scoped_loans` stopped filtering by membership. Behaviour was correct; the
invariant was simply unpinned. Now pinned, and verified by mutation — dropping
the tenant filter fails two of the three new tests.

Cross-partner isolation was deliberately **not** given a new test:
`apps/frontend/tests.py` already builds a second partner with same-shape
records and asserts non-visibility across two surfaces.

---

## 6. Domain board

Rated only where I hold first-hand evidence. Everything else is **Not Tested**,
which the mandate says must never be read as Green.

| Domain | Status | Basis |
| --- | --- | --- |
| Documents and policy | **Green** | four defects found, fixed, regression-tested |
| Automated quality pipeline | **Green** | every runnable gate passes |
| Deployment configuration | **Green** | prod `check --deploy` clean; boot guard verified; clean migration run |
| Data integrity (money/verification) | **Green** | §31 families return zero on seeded data |
| Authentication and access | **Amber** | SEC-A1 fixed and pinned; `has_permission` / `can_view_page` fail closed for anonymous; fourteen roles open every permitted argument-free page in CI; OBS-2 leaves the matrix unable to distinguish guarded from unguarded |
| Priorities and targets | **Amber** | SEC-A4 fixed; CONFLICT-003 and OBS-1 open |
| Loans and MFI | **Green** | cross-tenant isolation proven over HTTP and now regression-pinned (SEC-A5); confidential loan fields withheld from CCEO, PL and Admin |
| Partners | **Green** | cross-partner isolation proven over HTTP; already pinned in `apps/frontend/tests.py` |
| Budget and fund workflow | **Green** | exactly-once disbursement, reimbursement and partner payment proven by concurrent tests against real PostgreSQL, passing in the suite run here |
| Integrations | **Red** | no transport exists (B-3) |
| Mobile and offline | **Red** | capability absent (B-4) |
| Container supply chain | **Green** | image builds, runs non-root, imports, and carries no fixable CRITICAL/HIGH (CI, head `2248cdf5`) |
| Backup / restore / rollback | **Not Tested** | no production access |
| Performance and scale at 50k | **Not Tested** | not runnable here |
| Planning and scheduling | **Red** | not a defect but a scope collision: the calendar, entitlement, frequency-cap and catalogue-eligibility blocks §20.2 requires were removed from the scheduling path on `main` during this audit (CONFLICT-004) |
| All remaining domains | **Not Tested** | not reached in this pass |

---

## 7. What would change the verdict

1. **B-1 and B-2 are fixed** in this branch and need review and merge.
2. **B-3 and B-4 are scope decisions, not engineering work.** Descope them in
   writing — manual Salesforce reconciliation stated plainly in the release notes,
   offline field operation deferred with "field staff need connectivity" said out
   loud — and they become disclosed limitations rather than blockers.
3. **CONFLICT-004 has to be answered first.** The scheduling governance §20.2 requires was deliberately removed from `main` while this audit was open. Until someone says whether the mandate's scheduling section still stands, the Planning and scheduling gates cannot be assessed — they would be measuring the release against a rule the product has just discarded.
4. The rest is ops, and one item is now closed: CI built and scanned the image on the
   audit head and it carries no fixable CRITICAL or HIGH, so **CVE-2026-14456 is no
   longer an open blocker**. What remains is to restore from a production backup
   once, rehearse the rollback, run the production smoke, and name an incident owner.

None of that needs more code review. Four of the five items have not been done at
all. A deadline arriving is not evidence, and the one P0 in this report was live on
`main` this morning.
