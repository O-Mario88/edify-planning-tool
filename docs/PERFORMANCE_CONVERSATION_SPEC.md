# Performance Conversation — Engineering Specification

**Status:** Spec (not yet fully wired against the existing engine)
**Owners:** HR + Platform
**Related code:** `apps/hr/models.py` (`PerformanceCycle`, `ReviewStage`), `apps/hr/performance_engine.py`, `apps/hr/performance_service.py`

> The performance review today lives in a manually-circulated HR document
> that separates employee, line-manager, and functional-manager assessment,
> then applies an overall rating and signatures after leadership review.
> This spec replaces that document with a **controlled, real-time, HR-gated
> workflow** that preserves the governance structure while removing manual
> re-entry of data the platform already holds.
>
> **One rule runs through everything:** the conversation is a *review*,
> not an *always-open* form. Only HR opens it, only HR locks it, and no
> one signs their own record.

---

## Purpose

The system automates data preparation; humans keep the reflection,
judgement, support, and due process. Each conversation must answer:

- What priorities did the employee agree to deliver?
- What milestones were expected by this review date?
- What verified progress has been achieved?
- What additional responsibilities did the employee perform?
- What operating conditions affected delivery?
- What support did the manager provide?
- What development has occurred?
- How has the employee demonstrated Edify Values?
- What should continue, change, or receive support?
- Is normal coaching sufficient — or is a Recovery Plan, formal PIP
  review, or a restricted separation conversation required?

---

## Glossary

Defined on first use because this codebase treats undefined acronyms as a
defect (`docs/PRODUCT_PRINCIPLES.md` — Simple).

| Term | Meaning | Source |
|---|---|---|
| **SSA** | School Self-Assessment — the school-level quality instrument | `apps/analytics/ssa_performance_service.py` |
| **SSA completion** | A staff target: % of a staff member's allocated schools with a verified current-FY SSA. **Legitimate performance measure.** | §12 |
| **School SSA score** | The school's measured outcome. **Not** a staff measure — it reflects conditions outside any one employee's control. | §11 |
| **PIP** | Performance Improvement Plan — the formal recovery process; only ever started by HR, never by a score. | `apps/hr` migration `0006` |
| **CCEO** | Cluster Church Education Officer — school-facing field staff | `apps/core/rbac.py:24` |
| **PL** | Program Lead — supervises CCEOs | `EdifyRole.COUNTRY_PROGRAM_LEAD` |
| **IA** | Impact Assessment role | `EdifyRole.IMPACT_ASSESSMENT` |
| **CD** | Country Director | `EdifyRole.COUNTRY_DIRECTOR` |
| **RVP** | Regional Vice President | `EdifyRole.REGIONAL_VICE_PRESIDENT` |
| **Functional manager** | A configured technical/functional reviewer distinct from the line manager (e.g. finance for an Accountant). Optional per role template. | §6 |
| **SLT** | Senior Leadership Team — the calibration body for final ratings | `ReviewStage.READY_FOR_SLT_CALIBRATION` |
| **MSCS** | "Most Significant Change Story" — a captured story that counts toward a target once approved | `my-targets/mscs` |
| **Snapshot** | An immutable copy of all source data at the moment HR opens a conversation; everything downstream is built from it. | §4 |

---

## 1. Invariants (non-negotiable)

These hold at all times. Every other section exists to enforce them.

1. **HR-gated.** No conversation is editable unless HR has opened it. Only HR may open, reopen, close, and lock a cycle.
2. **Role-scoped.** Every actor participates only at their assigned workflow stage. A user may never sign or assess their **own** record as manager, country approver, or HR approver.
3. **Signature integrity.** A signed section is immutable. If material content below a signature changes, that signature is invalidated and the record returns to the earliest affected stage for re-sign. Original signed versions are preserved in history; completed records are never overwritten.
4. **Source of truth.** No manual re-entry of data that already exists in My Targets, Team Targets, Special Projects, Professional Development, Activities, School Portfolios, or other canonical modules. No progress value may be manually overwritten.
5. **No double-counting.** Partner work is not direct staff execution; supervised-team work is not the manager's personal execution; no activity counts twice.
6. **No score-driven severity.** No PIP and no separation process is started automatically from a numeric score. Both require HR + human judgement.
7. **SSA boundary.** No school SSA score directly determines staff performance. SSA *completion* may be a target; school SSA *outcomes* are programme context, not staff causality.
8. **Auditable.** Every transition, assessment, return, signature, reopen, and lock is written to a tamper-evident audit trail. Direct status mutations are forbidden — all movement goes through one `PerformanceConversationTransitionService`.

---

## 2. Canonical routing

Routing follows the configured reporting relationship, never hardcoded page
logic. Roles are defined in `apps/core/rbac.py`.

| Employee role | Line reviewer | Country sign-off | Final HR sign-off |
|---|---|---|---|
| CCEO | Program Lead | Country Director | HR |
| Program Lead | Country Director | Same CD — **do not duplicate** | HR |
| Impact Assessment | Country Director | Same CD | HR |
| Project Coordinator | Country Director | Same CD | HR |
| Program Accountant | Country Director | Same CD | HR |
| Country Director | RVP | n/a — CD cannot sign own review | HR |
| Country HR | RVP | CD acknowledgement configurable, but HR cannot sign own record | **Independent** HR reviewer or regional HR |
| RVP | Configured executive supervisor / SLT authority | n/a | **Independent** HR reviewer |

Two rules prevent signature churn:

- **No duplicate CD signatures.** Where the CD is already the line manager (PL, IA, Project Coordinator, Accountant), use one combined CD-manager + country-approval stage. The platform must not request two CD signatures for one unchanged record.
- **Self-review prohibition, enforced for HR.** When the employee under review is an HR employee, route the final sign-off to an independent authorized HR reviewer, a regional HR authority, or an approved Admin governance role.

Where a **functional manager** is configured, they assess *after* the line manager and *before* country sign-off. HR decides per role template whether that input is Required / Optional / Not applicable. An absent *optional* functional manager must not stall the workflow; an absent *required* one surfaces as a readiness issue before the conversation opens (§5).

---

## 3. Workflow state machine

One canonical machine. No direct status mutations; all movement through
`PerformanceConversationTransitionService`. This supersedes (and is intended
to replace) the existing free-string `ReviewStage` where it overlaps — see
the migration note at the end of this section.

```
Scheduled
 → HR Readiness Review
 → HR Opened                       [snapshot frozen; employee notified]
 → Employee In Progress
 → Employee Signed                 [employee section locked]
 → Manager Review
 → Manager Signed
 → Functional Manager Review      (where configured)
 → Functional Manager Signed
 → Country Director Review
 → Country Director Signed
 → HR Final Review
 → HR Signed
 → Completed
 → Locked                          [immutable; DOCX + PDF generated]
 → Archived
```

**Exceptional states** (reachable from the main line, then re-joined or
terminated): `Not Ready`, `Returned to Employee`, `Returned to Manager`,
`Correction Required`, `Reopened by HR`, `Priority Amendment Required`,
`Performance Support Review`, `PIP Review Pending`, `PIP Active`,
`Separation Review`, `Cancelled`.

**Migration note:** `apps/hr/models.py:ReviewStage` already encodes part of
this chain (`PRIORITIES_*`, `MANAGER_REVIEW_COMPLETE`,
`FUNCTIONAL_MANAGER_COMPLETE`, `HR_QUALITY_REVIEW`,
`READY_FOR_SLT_CALIBRATION`, `SLT_CALIBRATED`, …). The implementation work is
extending it to the full chain above and funnelling every write through the
transition service, *not* designing a second parallel vocabulary.

---

## 4. Opening — snapshot and the employee stage

**When HR opens the conversation:**

1. Create an **immutable performance-data snapshot** from all canonical modules (§9). Live data stops mattering from this point; downstream stages read the snapshot.
2. Notify the employee.
3. Create a To-Do with a direct link.

**Employee-editable fields** (the only fields the employee may touch):

- Employee reflection, per priority
- Achievement explanation; challenges & barriers
- Support received; support still required
- Additional work performed; additional Project contribution
- Professional Development reflection; Spiritual Formation reflection; Edify Values reflection
- Employee self-rating; summary comment
- Acknowledgement of system-generated data; employee signature

**The employee may NOT edit** (system- or reviewer-owned): approved priority
definition & target; verified My/Team Targets values; closed Activity totals;
SSA completion records; Special Project assignments; PD source records;
school portfolio size; operating-context data; and every reviewer section
(manager / functional / CD / HR comments and ratings).

**On employee signature:** validate required sections → record signature,
timestamp, role, snapshot version → **lock the employee section** → notify
the correct line manager (§2) → create the manager To-Do.

---

## 5. HR-controlled windows

Conversations stay **locked** outside an HR-authorized window.

**Cycle types:** FY Priority Setting · Q1 · Mid-Year (Q2) · Q3 ·
End-of-Year (Q4) · Performance Support Conversation · PIP Review ·
Separation Conversation.

**Fiscal-year quarter structure** (note the offset from calendar Qs):

| Label | Months | Notes |
|---|---|---|
| Q1 | Oct–Dec | |
| Q2 | Jan–Mar | **Mid-Year Review** |
| Q3 | Apr–Jun | |
| Q4 | Jul–Sep | **End-of-Year Review** |

**T−7 days before each quarter end**, automatically notify HR that the window
is due for readiness review. The readiness notification must surface:
employees expected in the cycle; missing approved priorities; missing direct
*or* functional managers; employees/managers on leave; missing My Targets,
Team Targets, Project, or PD data; incomplete source-data sync; temporary
delegation required; and records not yet ready to open.

**HR openable scopes:** the full organization, one country, one team, one
role, one employee, or a controlled correction window.

**Every** opening, extension, reopening, closing, and locking action requires
a reason and writes to the audit trail (Invariant 1, 8).

---

## 6. Reviewer stages

Each stage below has the same shape: a defined remit, an explicit
"may not" list, and a signature that locks the stage and routes onward.
No reviewer may rewrite an earlier signed section.

### 6.1 Line manager (after employee signature)

**May:** review automatic progress, employee reflection, evidence links,
additional responsibilities, workload & operating context; add comments and
a priority-by-priority assessment; add development recommendations and
support commitments; record agreed actions; recommend Priority Amendment,
Recovery Plan, or HR Performance Support Review; provide the manager rating;
sign the stage.

**May not:** change verified progress; edit the employee reflection; change
source Activities / SSA / Project / finance / PD records; start a PIP or
separation directly (recommendation only — HR decides).

### 6.2 Functional manager (where configured)

Assesses functional quality, technical competence, data quality,
professional standards, cross-team contribution, role-specific observations;
provides a functional rating, development recommendation, and signature.
Per-role-template setting (Required / Optional / N/A) controls whether
absence stalls the workflow (§2).

### 6.3 Country Director sign-off

Reviews employee priorities, verified progress, the employee + manager +
functional-manager assessments, additional Projects/assignments, portfolio
complexity, and district/school context. May agree, return to manager,
request clarification, add country-level comments, confirm the country
assessment, and sign off. **Must not** rewrite the employee or manager
sections.

- For PL / IA / Project Coordinator / Accountant where the CD is already the line manager → **one combined stage**, not two CD signatures (§2).
- For the CD's own conversation → route directly to RVP; the CD never country-signs their own review.

### 6.4 RVP sign-off

Reviews CD conversations, Country HR conversations where RVP is the manager,
and other configured direct reports — plus country-level context, strategic
responsibilities, additional regional assignments, leadership results, and
operating complexity. May add a leadership assessment, request
clarification, return the conversation, confirm the rating, and sign off.
RVP access is limited to authorized records and appropriately scoped
supporting information.

### 6.5 Final HR review and signature

HR's signature confirms **process integrity**, not performance judgement:
correct workflow followed; correct reviewers participated; required fields
complete; required signatures present; ratings on the approved scale;
PIP/separation recommendations follow policy; **no self-approval occurred**;
source data traceable; required amendments recorded; record ready to lock.

HR does **not** replace the manager's performance judgement; HR signs for
policy compliance. For HR employees, use an independent reviewer (§2).

---

## 7. Locking and reopening

### Lock (HR only)

HR may lock **only when**: employee, manager, required functional manager,
CD (where applicable), RVP (where applicable), and HR have all signed;
required comments exist; mandatory actions have owners; ratings are valid;
amendment issues resolved; the generated document matches the final
snapshot.

Locking must: make the record immutable; generate the final **DOCX + PDF**;
archive the snapshot; store all signatures; publish agreed actions; create
follow-up To-Dos; update the performance dashboard; write the audit event;
notify employee and manager.

### Reopen (HR only)

Requires reason, affected section, requester, authorizer, timestamp,
previous version, new version. **On material content change:** invalidate
all affected downstream signatures, return the workflow to the earliest
affected stage, require re-review and re-sign, preserve the original signed
version, and never overwrite completed history (Invariant 3).

---

## 8. Automatic data population

This is the point of replacing the manual document: the system prepares the
measurable evidence so humans can reflect, judge, and support. **No manual
re-entry** (Invariant 4).

### Milestones & progress

Populate measurable priorities from **My Targets**; for managers also
populate authorized **Team Targets**. Employee-level auto fields: monthly /
quarterly / Mid-Year / FY targets, expected- and actual-to-date results,
achievement %, remaining target, verified source records, target status,
data confidence. Manager-level info must **separate** the manager's own
targets from direct-report targets, team aggregate, team risk, team
progress, partner contribution, and Project contribution.

### Priority data sources (by priority type)

- **Program Growth:** verified new schools, new Core Schools, school activation, retention (where configured), Church engagement, approved growth Activities.
- **Program Quality:** School Visits, Training, **SSA completion**, Core Assessment, Cluster Meetings & Training, MSCS, evidence/Salesforce/accountability quality.
- **Professional Development:** approved course, provider, dates, funding, status, certificate, BambooHR confirmation, accountability, NetSuite verification, skills gained.
- **Special Projects:** assigned Projects, project role & schools, Project Activities, verified deliverables, partner involvement, budget responsibility, outcomes, risk, additional-assignment period.
- **School portfolio:** total assigned, direct-support, partner-supported, Core/Client mix, Projects, Clusters, districts, secondary-district workload.

### Manual sections (employee-owned reflective content)

Spiritual Formation priorities & reflection, Edify Values reflection, part
of the PD reflection, additional work not already captured, context or
barriers, and summary comments. Edify Values: *Christ-like Service ·
Devoted to Prayer · Transformation through Relationships · Excellence &
High Integrity · Entrepreneurial Spirit · Best Idea Wins* — for each value
capture agreed behaviour, employee reflection, manager observation, growth
commitment. **Never auto-score values from Activity counts.**

### Additional Projects & additional work

Overall performance must recognize work beyond the original agreement.
Auto-fetch additional Projects from Special Project assignments, Project
Coordinator assignments, Project Activities, Leadership Actions, approved
special assignments, and cross-team support records. Allow employees to
nominate additional work not auto-captured — such a claim needs
description, period, requesting leader, beneficiary team/Project, evidence,
time/workload impact, expected vs actual result — and the **manager must
validate** before it affects the assessment. **Block duplicate credit**
where one activity appears as normal target work, Project work, additional
assignment, and team contribution (Invariant 5).

---

## 9. Fair evaluation, SSA, and operating context

### 9.1 Role-based weighted evaluation

Overall performance is **not** raw target percentage. Use a configurable
role-based framework. **Default weights** (HR may reweight per role
template, but an employee's approved weighting must not change silently
mid-FY):

| Dimension | Default |
|---|---|
| Approved Priorities & Target Achievement | 50% |
| Execution Quality & Workflow Discipline | 15% |
| Additional Projects & Additional Responsibilities | 10% |
| Portfolio, Workload & Operating-Context Complexity | 15% |
| Professional Development, Spiritual Formation & Edify Values | 10% |

Every final assessment displays: raw target achievement; quality result;
additional-responsibility contribution; operating-context profile; values &
development assessment; **suggested** overall rating; manager final rating;
CD/RVP confirmation; and **a mandatory reason for any variance** from the
suggested rating.

### 9.2 SSA completion ≠ school SSA score (Invariant 7)

**SSA completion target** (legitimate): % of allocated schools with a valid
current-FY verified SSA, plus timeliness, data completeness, and data
quality.

**School SSA score** must **not** directly reduce an employee rating,
because it may reflect rural location, poor road access, long travel
distances, no electricity, sub-standard classrooms, insufficient
facilities, unqualified teachers, teacher shortages, low/irregular
school-fee payment, household poverty, leadership instability, community
conditions, government limitations, or historical underinvestment.

Instead, evaluate the staff member on whether they: completed required SSA,
used recommendations correctly, planned appropriate support, executed
planned interventions, provided valid evidence, followed up schools,
escalated structural barriers, managed Partners effectively, maintained
data quality, completed accountability, and used resources responsibly.
SSA score changes appear as *programme outcome context / intervention
progress / contribution evidence / learning information* — never labelled
as direct employee causality.

### 9.3 Operating-context profile

A canonical `WorkloadAndContextService` builds an evidence-based profile
from verified, dated, traceable data only: school counts (total / direct /
partner-supported / Core-Client mix), Projects, Partners managed, Clusters,
districts, average daily distance, secondary-district travel, hotel nights,
road-condition classification, rural-school %, electricity availability,
classroom & facility condition, teacher qualification & shortages,
school-fee payment challenges, enrollment pressure, government-requirement
challenges, approved leave, transport interruptions, funding delays, school
closures. Show **data confidence** (High / Medium / Low). **Never
fabricate** context values or allow an unsupported subjective complexity
score.

### 9.4 Context-adjusted *target setting*

Use operating conditions **when setting targets**, not only after
performance. At FY Priority Setting, calculate proposed direct-school
allocation, reasonable Visit/Training expectations, Project capacity,
travel load, Partner-management load, and recommended target phasing;
employee + manager review the recommendation; HR validates fairness;
targets lock. If conditions materially change mid-FY → generate a
Priority Amendment recommendation; **never silently lower or raise** the
target.

### 9.5 Performance-context display

Separate panels — Performance Against Agreed Priorities · Quality &
Timeliness · Additional Projects & Contributions · Portfolio & Workload
Complexity · District Operating Conditions · School Context · Professional
Development · Spiritual Formation & Values. **Never** collapse every
factor into one unexplained percentage. The suggested rating shows how each
component contributed; the final human rating may differ, with a mandatory
reason.

### 9.6 Rating scale

`Far Exceeds Priority · Exceeds Priority · Met Priority · Met Some
Priority · Did Not Meet Priority`. Maintain separate ratings: employee ·
manager · functional-manager · country/regional confirmation · final
calibrated. The system **may suggest** from verified evidence but **must
not finalize** automatically. For capped targets (e.g. 100% SSA
completion), exceeding the denominator does **not** automatically mean Far
Exceeds — that rating requires approved additional scope, exceptional
quality, early completion, support to other staff, significant additional
responsibility, or strong verified execution under high complexity.

---

## 10. Real-time dashboards

Use canonical Domain Events + SSE (or the approved real-time mechanism).
On every stage change, update the relevant dashboard immediately with
**zero** allowed mismatch. Events: opened, employee started/signed,
manager/functional/CD/RVP review-ready and signed, HR final-ready and
signed, locked, returned, reopened, Priority Amendment required, Recovery
Plan recommended, PIP review requested, document generated.

- **Employee dashboard:** current status, current owner, deadline, employee completion %, auto-progress readiness, missing manual sections, signature status, returned comments, next action, downloadable documents. An employee must never see an editable conversation HR hasn't opened.
- **Manager dashboard:** conversations awaiting employee / awaiting manager review / employee-signed & ready / overdue / returned / completed, priority risk, target & Team-Target progress, context alerts, recovery recommendations, upcoming deadlines. PL sees only supervised CCEOs; CD sees authorized country employees; RVP sees authorized direct reports + regional governance.
- **Country Director dashboard:** country completion, pending CD sign-offs, records already manager-reviewed, missing manager signatures, rating distribution, priority achievement, additional-Project contribution, high-complexity portfolios, Performance Support recommendations, PIP review requests, overdue records, HR readiness exceptions. **Do not expose** unrestricted confidential HR case details.
- **HR cycle dashboard (control center):** cycle status, window open/locked, employees in scope, readiness %, missing priorities/source-data/managers, employee/manager/functional/CD/RVP completion, HR final-signature queue, overdue/returned/reopened/amendment records, Recovery Plans, PIP & separation reviews, generated documents, audit exceptions. Primary actions: Review Readiness · Open Window · Extend Deadline · Send Reminder · Return Record · Reopen Record · Lock Completed Cycle · Generate Documents.

---

## 11. Notifications, To-Dos, SLA & coverage

**Handoffs:** at each handoff notify the next responsible person, create
one To-Do with a direct link + deadline, resolve the previous To-Do, and
prevent duplicate notifications. Required notifications: HR readiness
(T−7), conversation opened, employee/manager/functional/CD/RVP/HR action
required, returned for correction, deadline approaching, overdue,
completed, document available.

**Every stage carries:** opened date, due date, age, SLA, owner, delegate
(where applicable), escalation state.

**Leave & delegation:** if a manager is on approved leave, resolve the
configured temporary delegate, grant only the required conversation-review
permission scoped to the affected employees, and **auto-expire access**
after the coverage period. A manager's leave must not freeze the whole
cycle. Do **not** auto-delegate restricted PIP/separation authority
without explicit HR approval.

---

## 12. Document generation

Generate from the **final locked snapshot** only. Outputs: Performance
Conversation DOCX, locked PDF, online record. Include: employee details,
role, manager, functional manager, country & HR reviewers, conversation
period, approved priorities/milestones/targets/progress, all ratings,
employee reflections, manager/functional/country-or-regional comments,
additional Projects & work, operating context, PD, Spiritual Formation,
Edify Values, agreed actions, overall rating, signatures, dates, template
version, snapshot version, amendment history.

Every download is permission-checked, scope-checked, audit-logged, and
generated from a locked version.

---

## 13. Required tests

Each maps to an invariant or routing rule above. Names suggest the
assertion.

**Lifecycle & gating** — locked before HR opens; only HR opens; only HR
closes/locks; employee edits only the employee stage; employee signature
locks employee fields; no employee edits manager assessment; no manager
edits verified progress; HR locking generates DOCX + PDF; all role &
scope protections pass.

**Routing** — correct manager receives the handoff; CCEO→PL, PL→CD,
IA→CD, Project Coordinator→CD, Accountant→CD, CD→RVP, HR→RVP or
configured supervisor; CD does not sign own conversation; HR does not
self-sign; CD country sign-off not duplicated where CD is already manager;
required functional-manager stage works; optional functional-manager stage
does not stall; HR receives the final record.

**Signature integrity** — reopening invalidates affected downstream
signatures; historical versions remain unchanged.

**Data population** — My Targets populate employee progress; Team Targets
populate manager oversight; Special Projects populate additional
assignments; PD records populate the PD section; manual spiritual/values
sections stay editable only by the correct actor.

**Fairness** — SSA completion counts correctly; SSA score does not alter
staff performance; workload complexity calculated from verified data;
additional work requires manager validation; duplicate additional-work
credit blocked.

**Real-time & ops** — manager/CD/RVP/HR dashboards update in real time;
notifications & To-Dos hand off correctly; temporary manager coverage
works.

---

## 14. Done definition

The system is complete only when every **opening, snapshot, handoff,
review, signature, notification, document, permission, and locking rule**
works as one synchronized HR performance ecosystem — and the tests in §13
pass. A workflow that computes the right numbers but lets any invariant in
§1 slip is not done.
