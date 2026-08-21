# End-to-End Lending Platform Audit

**Audit date:** 20 August 2026  
**Scope:** Lending partners, funding facilities, school loans, disbursement,
repayment, loan use, impact, geography, permissions, integrations, UI,
auditability, and 50,000-school readiness  
**Code-readiness decision:** **APPROVED — DEPLOYMENT CONDITIONAL**  
**Unresolved Critical/High code findings:** **None**

This report records the implemented and automated-test evidence in this
repository. It does not invent production bank statements, Salesforce or
NetSuite credentials, object-storage secrets, backups, restore tests, or real
partner reconciliations. Those remain deployment evidence and must be supplied
in the target environment before production traffic is enabled.

## 1. Executive readiness

| Dimension | Result | Evidence |
|---|---|---|
| Lending Partner | Ready | Governed MFI organization, membership, admin/officer separation, tenant and assignment scope |
| Funding Facility | Ready | Facility, confirmed receipt tranche, allocation, capital movement, reversal, and position services |
| School Loan | Ready | Canonical school/MFI/reference, independent amounts and statuses, controlled amendment history |
| Disbursement | Ready | Immutable, idempotent, multi-tranche postings with facility over-allocation prevention and reversals |
| Repayment | Ready | Installments, transactions, component allocations, reversals, snapshots, arrears, PAR, default history |
| Salesforce | Ready | BT-only confirmation, unique validated ID, immutable confirmation record, durable retryable outbox |
| NetSuite | Ready | Confirmed facility receipts create idempotent durable outbox events when integration is enabled |
| Verification | Ready | Scheduled requirements, evidence submission, IA decision, concern review, activity linkage |
| Impact | Ready | Separate reported/verified evidence for enrolment, teachers, assets, purpose outputs, and assessments |
| Geography | Ready | Eligible-school denominators and most/least/no-loan rows, including zero-loan areas |
| Security | Ready | Role/record/field projection tests, cross-MFI denial, deploy checks, dependency and static security gates |
| UI | Ready | One canonical KPI strip, at most 6 globally, 4 on role dashboards, 2 on operational loan pages |
| Scale | Ready | 50,000-school bounded-query and sub-five-second service constraint |

Production recommendation: deploy only through the normal migration and
release process after environment-specific integration, storage, secret,
backup/restore, and real opening-balance reconciliations pass. The application
fails closed when required production settings are absent.

## 2. Domain and data-model report

The governed chain is:

`Funding Facility → Facility Allocation → School Loan → Loan Disbursement → Repayment → Loan-Use Verification → Loan Impact`

| Entity | Purpose and ownership | Principal controls |
|---|---|---|
| `MfiOrganization`, `MfiMembership` | Partner tenant and its users | Active membership, admin/officer role, organization and assigned-record scope |
| `FundingFacility` | One agreement/capital pool | Currency, dates, country/MFI ownership, status, capital source, agreement evidence |
| `FundingFacilityTranche` + reversal | Confirmed original cash receipt | Immutable/idempotent posting; confirmation evidence; reversal rather than mutation |
| `FundingFacilityMovement` + reversal | Deduction or return | Typed, immutable, idempotent movement with audit trail |
| `FundingFacilityAllocation` | Reserves facility capital for one loan | Facility/MFI consistency, capital-source split, over-allocation guard |
| `MfiLoan` / `SchoolLoan` proxy | Canonical school loan | Unique MFI reference; requested, approved, and derived disbursed amounts stay separate |
| `LoanDisbursement` + reversal | School cash tranche | Immutable/idempotent posting, bank evidence, allocation availability lock |
| `LoanRepaymentInstallment` | Contractual schedule | Due principal, interest, fees, penalties, and due date |
| `RepaymentTransaction` | Cash receipt or reversal | Immutable/idempotent transaction with posting date and evidence |
| `RepaymentAllocation` | Payment component allocation | Principal, interest, fee, and penalty remain independent |
| `LoanPurposeAllocation` | Planned/actual use of proceeds | Split amounts and percentages; governed purpose and verification state |
| `EnrolmentSnapshot` | Loan-time or follow-up enrolment | Reported and IA-verified evidence, not mutable school master data |
| `TeacherDegreeUpgradeBeneficiary` | Teacher programme beneficiary | Unique person key; enrolled and completed dates remain distinct |
| `PurposeSpecificAssetOutput` | Classroom, land, computer, lab, or custom output | Planned/reported/verified quantity and evidence state remain distinct |
| `LoanPurposeProposal` | New-purpose governance | Request → BT review → measurement definition → approval/publish |
| `SalesforceConfirmation` | External identity assertion | BT-only, validated unique ID, immutable/idempotent record |
| `RepaymentSnapshot` | Period-end portfolio position | Principal outstanding, arrears days, independent repayment-health status |
| `PortfolioSubmission`, `PortfolioImportRow`, `PortfolioDataException` | Monthly return/import staging | Hash/idempotency, row validation, certification, exception correction |
| `LoanVerificationRequirement`, `LoanUseResult` | Use-of-funds assurance | Schedule, evidence, IA finding, concern-review closure |
| `LoanImpactAssessment` | Causally bounded outcome assessment | Baseline/follow-up, evidence, IA status, impact classification |
| `LoanAmendment`, `LoanStatusHistory` | Governed change history | Before/after payload, reason, actor, timestamps, idempotency |

Value-bearing posting models reject update/delete through their append-only
manager. Corrections are explicit reversals. Governed service actions also emit
central audit events with actor, subject, action, time, and details.

Independent dimensions are intentionally not collapsed:

- lifecycle: draft/submitted/approved/disbursed/repaid/cancelled/defaulted;
- Salesforce: pending/returned/confirmed;
- IA data validation;
- loan-use verification;
- impact assessment;
- repayment health/current-arrears-default position.

## 3. Financial reconciliation

### Facility position

For every facility the service returns approved/committed capital, confirmed
original receipts, recovered principal available for revolving use, original
and recovered allocations/disbursements, deductions, returns, and available
capital. Recovered principal is never presented as new funding received.

The controlling identities are:

```text
confirmed original capital = confirmed receipt tranches - receipt reversals
recovered capital = posted principal repayments - repayment reversals
available original = confirmed original capital - original allocations - deductions/returns
available recovered = recovered capital - recovered allocations - recovered returns
total available = available original + available recovered
```

Rows are locked for allocation/disbursement posting. The services reject
cross-MFI facilities, allocation beyond confirmed availability, disbursement
beyond allocation or approved loan value, duplicate idempotency keys, and a key
reused with different facts.

### School-loan position

Each loan reconciliation exposes requested, approved, disbursed, purpose
allocated, principal repaid, outstanding principal, overdue amount/days, and
its independent lifecycle and health statuses. Disbursement and repayment totals
are derived from unreversed immutable transactions. A repaid loan cannot retain
an unexplained principal balance; default requires a date, reason, and history.

Monthly, quarterly, annual, and custom-period reporting separates activity in
the period from position at period end. The financial year is 1 October through
30 September. A rollover test proves a later-year repayment does not rewrite
the prior disbursement cohort.

## 4. Purpose, use, and impact reconciliation

Purpose intent, actual use, IA verification, and impact are different facts.
Mixed-purpose loans use allocations rather than duplicating the loan amount.
An inactive or newly requested purpose cannot silently enter final analytics;
the governed proposal requires a measurement profile before publication.

The impact view reports:

- unique financed schools, de-duplicated across repeat borrowing;
- students enrolled at financed schools, de-duplicated at school snapshot level;
- verified direct learner reach, separately labelled;
- unique teachers financed, enrolled, and completed;
- classrooms planned, built, and operational as separate measures;
- land reported and verified separately;
- computers purchased, installed, and functional separately;
- computer laboratories constructed, equipped, and operational separately;
- custom-purpose outputs only through the approved measurement definition.

Missing evidence remains unknown/pending; it is not converted to zero. Impact
classification uses evidence and a bounded attribution statement and does not
claim that the loan alone caused an outcome.

## 5. Geographic equity reconciliation

The geography service begins from the governed region/district/subcounty and
eligible-school population, not from loans. It therefore preserves eligible
areas with zero financing. Outputs include financed amount/count, eligible
schools, unique financed schools, penetration, amount per eligible school, and
purpose mix; the same rows support most-financed, least-financed, and no-loan
views and their record drill-downs.

## 6. Role and permission result

The detailed matrix is in
`docs/lending-role-permission-matrix-2026-08-20.csv`.

| Role | Read projection | Mutations |
|---|---|---|
| MFI Partner Admin | Own MFI operational portfolio | Register/manage own loans, returns, and partner membership |
| MFI Loan Officer | Own registered/assigned records | Register/correct permitted records; no tenant administration |
| Business Transformation | Complete governed operational portfolio | Salesforce, facility, exception, reconciliation, and workflow actions |
| Country Director | Complete country oversight | Specified approvals, returns, concern and exception decisions |
| Impact Assessment | Complete required assurance detail | Data, loan-use, and impact verification/return actions |
| Regional VP | Complete approved regional read view | Read-only |
| Program Lead / CCEO | Financed schools and verified impact only | Approved impact/field actions; no financial fields |
| Accountant | Facility transfer/evidence projection only | Approved transfer evidence only |
| Admin | No implicit lending access | No implicit lending mutation |

Controls are enforced at page permission, queryset/object scope, serializer,
API, and export boundaries. Automated negative tests cover cross-MFI IDs,
record ownership, role restrictions, and the absence of financial fields from
impact-only projections.

## 7. Operational handoffs, exceptions, and integrations

Workflow-derived To-Dos and notifications cover Salesforce submission and
return, IA validation, loan-use scheduling/evidence/concerns, impact and
enrolment review, repayment risk, new-purpose approval, stale repayment data,
portfolio import errors, monthly returns, and geographic gaps. Their source
state is authoritative: when the state is resolved, the task disappears or the
notification is archived.

Salesforce and NetSuite use the durable integration outbox. Every event has an
idempotency key, current state, attempt count, response/error detail, and retry
path. Confirmation remains valid only when the immutable local fact is present;
failed delivery does not manufacture a successful external state. Bulk MFI
imports stage immutable source rows, validate them, isolate row exceptions,
and apply normalized facts idempotently.

## 8. UI/UX and accessibility result

The application now uses `templates/components/kpi_strip.html` as the sole KPI
tile renderer. The inventory contains 65 shared-component summary surfaces and
zero legacy summary surfaces. Limits are:

- no more than 6 KPI tiles on any desktop page;
- no more than 4 on lending role dashboards;
- no more than 2 on operational loan pages;
- responsive two-column tiles on mobile;
- one consistent card anatomy: icon/tone, optional trend/status, label, value,
  drill-down link, rounded border, restrained shadow, and accessible focus.

The authenticated route/DOM audit covers 559 argument-free routes across 14
roles (7,826 role/route responses). It rejects 500 responses, legacy KPI card
families, missing canonical anatomy, and pages above the global six-tile limit.
The mobile source-order regression keeps the role/platform pulse before
`Critical Now`, including the project surfaces cited in the UI review.

## 9. Security, quality, and scale evidence

| Gate | Result |
|---|---|
| Django system check | Pass |
| Pending migration check | Pass |
| Production deploy check with validation-only secure environment | Pass |
| Python dependency vulnerability audit (`pip-audit --strict`) | Pass — no known vulnerabilities |
| Node production dependency audit | Pass — 0 vulnerabilities |
| Bandit configured medium-or-higher severity/confidence scan | Pass — no reportable issues |
| Ruff lint and repository format check | Pass |
| KPI inventory and ratchets | Pass — 417 registered metrics, 170 breakdown rows, 65 canonical summaries, zero legacy families |
| Authenticated route/DOM matrix | Pass — 7,826 responses |
| Lending focused/unit/contract/scale tests | Pass |
| Complete Django suite | Pass — 5,506 tests in 951.798 seconds; 2 intentional skips, 1 expected failure |
| 50,000-school service constraint | Pass — bounded query count and under 5 seconds inside the assertion |

Expected 400/403/404/405 responses in negative route/security tests are not
failures. Production settings intentionally reject development secrets, shadow
authentication, missing private storage, missing encryption keys, or missing
shared cache configuration.

## 10. Acceptance journeys and gates

All 20 mandatory journeys are represented by automated tests: facility to loan,
MFI entry/Salesforce, duplicate detection, enrolment discrepancy, classroom,
land, computer, laboratory, teacher degree upgrade, mixed purpose, repayment,
arrears/default, repeat borrower, no-loan geography, restricted PL/CCEO access,
cross-MFI denial, new purpose, integration failure/retry, financial-year
rollover, and revolving capital.

All code-verifiable gates in section 42 pass. The evidence specifically proves
tenant scope, canonical schools/references, separate ledgers/statuses, facility
and repayment reconciliation, verified impact semantics, role projection,
drill-down, amendments/audit history, automatic task closure, recoverable
integrations, stable historical cohorts, and 50,000-school bounded scale.

## 11. Data-quality register

| Risk | Detection/prevention | Release state |
|---|---|---|
| Duplicate loan/import | Tenant reference constraint, duplicate match, hashes/idempotency | Controlled |
| Missing enrolment | Explicit missing state and IA exception path | Controlled |
| Unmapped purpose | Governed proposal; excluded until measurement profile/publish | Controlled |
| Stale repayment | Dated snapshot check and derived MFI To-Do | Controlled |
| Invalid balance | Ledger-derived reconciliation and invariant checks | Controlled |
| Missing evidence | Reported/verified state and assurance queues | Controlled |
| Invalid status combination | Independent enums, service transition guards, history | Controlled |
| Unauthorized access | Default-deny role/object/field tests and audit logging | Controlled |

## 12. Remediation and deployment roadmap

There are no remaining Critical or High implementation findings in the audited
scope. The remaining work is environment- or operations-specific:

1. Before pilot: migrate a copy of real opening facilities, loans, repayments,
   purposes, evidence, and geography; reconcile every difference with named
   owners and sign-off.
2. Before production: configure strong secrets, field encryption, private
   object storage, shared Redis, Salesforce and NetSuite credentials, worker
   queues, alerting, backups, and a successful restore drill.
3. Within 30 days: measure production reconciliation exceptions, retry backlog,
   To-Do closure, access-denial anomalies, and query latency against SLOs.
4. Within 90 days: conduct an independent penetration test and sample-based
   financial/impact evidence audit.

## 13. Answers to the 40 final audit questions

Questions 1–39 are answered **yes by implemented code and automated evidence**:
the platform identifies and reconciles facilities and school loans; separates
original/recovered capital, amount stages, disbursement tranches, repayment
components, statuses, verified use and impact; de-duplicates schools/students
and teachers; preserves staged asset outcomes; governs new purposes; reports
complete geography including zero-loan areas; supplies the required role views;
protects sensitive fields; drills aggregates to records; reconciles periods;
routes/auto-closes handoffs; retries failures; preserves fiscal history; and
meets the 50,000-school service constraint.

Question 40 is answered: **the code is ready for a controlled production
release, conditional on the environment and real-data sign-offs in section 12.**
That distinction is deliberate: repository tests can prove implementation
controls, but only deployment evidence can prove credentials, external systems,
opening balances, backups, and live operating effectiveness.
