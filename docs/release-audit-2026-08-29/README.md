# Release readiness audit — 2026-08-29

**Verdict: NO-GO.**

| | |
| --- | --- |
| Release candidate audited | `b5b1741c1d8193a326aed079568cb6c2f08bd8f7` (= `origin/main` at audit start) |
| Audit branch | `claude/edify-production-readiness-audit-xgl7jx` |
| Environment | PostgreSQL 16, Redis 7, Python 3.13, live checkout |
| Final suite | 6,228 tests, `OK`, at `68ed46c25a379edc9f5dc7c7241bb6c8390e8e65` |

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
| CONFLICT-003 | RVP also holds `milestones.define`. Mandate §18.1 says "RVP and Admin remain read-only for business values"; `apps/hr/priority_cascade.py` has the RVP authoring strategy. Two sources genuinely disagree. | §3 requires a conflict be registered and decided by the product owner, not resolved silently inside an audit fix. The Admin half had three sources agreeing and was fixed. |
| OBS-1 | `Permission.STRATEGIC_PRIORITIES_EDIT` is granted to four roles and checked nowhere — it appears only in `rbac.py`. The real gate is `milestones.define`. | Gates nothing today. Latent: adding one decorator would hand RVP and Admin an authority nobody re-reviewed. Removing it deletes the scaffold for an approved extension (§4). Needs a decision, not a patch. |
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
| Container build, non-root check, runtime import, Trivy scan | No Docker daemon here. **CVE-2026-14456** (OpenSSL QUIC DoS, HIGH), raised by the prior audit as A-1, therefore still has no evidence of remediation. |
| Production smoke test | No production access. |
| Restore from a production backup | No managed database. Never performed (prior audit A-3). |
| Rollback and deployment rehearsal | No deploy target. |
| Monitoring, alert delivery, named incident owner | Organisational. |
| 50,000-school scale | The repo's own gate measures 15,000; full scale needs production-equivalent hardware. |
| Physical device / browser / orientation matrix | No devices. |
| Real integration sandboxes | None exist to point at — see B-3. |
| Browser journeys (Playwright) | Environment prepared; not run in this pass. |

Nine of the mandate's §40 gates sit in this table. None can be called Green.

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
| Authentication and access | **Amber** | SEC-A1 fixed and pinned; `has_permission` / `can_view_page` fail closed for anonymous; OBS-2 leaves the matrix unable to distinguish guarded from unguarded |
| Priorities and targets | **Amber** | SEC-A4 fixed; CONFLICT-003 and OBS-1 open |
| Integrations | **Red** | no transport exists (B-3) |
| Mobile and offline | **Red** | capability absent (B-4) |
| Container supply chain | **Not Tested** | no Docker daemon |
| Backup / restore / rollback | **Not Tested** | no production access |
| Performance and scale at 50k | **Not Tested** | not runnable here |
| All remaining domains | **Not Tested** | not reached in this pass |

---

## 7. What would change the verdict

1. **B-1 and B-2 are fixed** in this branch and need review and merge.
2. **B-3 and B-4 are scope decisions, not engineering work.** Descope them in
   writing — manual Salesforce reconciliation stated plainly in the release notes,
   offline field operation deferred with "field staff need connectivity" said out
   loud — and they become disclosed limitations rather than blockers.
3. The rest is ops: build and scan the image to clear CVE-2026-14456, restore from a
   production backup once, rehearse the rollback, name an incident owner.

None of that needs more code review. None of it has been done. A deadline arriving
is not evidence, and the one P0 in this report was live on `main` this morning.
