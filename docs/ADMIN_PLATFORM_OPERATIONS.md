# Admin as Platform Operations

**Governing principle** — Admin can observe the entire operational ecosystem,
but does not own or execute field-programme workflows. Admin's own work is
system maintenance, user support, incident resolution, controlled data repair,
platform improvements, releases and security response.

---

## 1. What changed, and why it mattered

`ROLE_PERMISSIONS[EdifyRole.ADMIN]` was `list(Permission)`. Admin held every
permission on the platform — including permissions that did not exist when that
line was written, because the grant was open-ended. In practice Admin could
schedule field activities, upload evidence into the IA chain, verify as Impact
Assessment, approve weekly and monthly fund requests, and disburse money.

Several existing tests had quietly encoded this. Three of them asserted a role
held a permission "**alone**" while listing Admin alongside it:

```python
self.assertEqual(
    holders,
    {EdifyRole.IMPACT_ASSESSMENT.value, EdifyRole.ADMIN.value},
    "activity verification is Impact Assessment's authority alone",   # it was not
)
```

The grant is now **derived**: Admin receives every permission that is not in
`ADMIN_EXCLUDED_PERMISSIONS`. A new permission reaches Admin by default only if
it is not an execution right, which is the opposite of the failure mode above.

## 2. The line

Admin **maintains school data**; Admin **makes no field judgement about it**.

| Admin does | Admin does not |
| --- | --- |
| Upload schools · upload SSA files · edit schools | Confirm an SSA record (`ia.verify`) |
| Reach every school in the country | Plan or schedule a visit, training or cluster meeting |
| Record cluster membership and project membership | Assign work to a delivery partner |
| Resolve duplicates, delete school master data | Upload evidence, review evidence |
| User administration, roles, configuration, geography | Approve fund requests (weekly, monthly, escalated) |
| System health, incidents, releases, maintenance | Disburse, hold, release or return money |
| Controlled data repair | Clear accounts, close activities |

Two judgement calls, both stated so they can be reversed:

* **Cluster membership and project membership are registry data.** Which
  cluster a school belongs to, and which project it participates in, are
  records — the same class of thing as the school row itself. Scheduling that
  cluster's meetings or that project's work is execution and stays cut.
* **Deleting execution records is now refused for every role**, Admin included.
  An activity carries budget lines, evidence state and target credit; deleting
  one from an ordinary page erases that history. Repairs go through the Data
  Repair Center. School and cluster master data stay Admin-deletable.

## 3. Enforcement, in three layers

1. **Matrix** — `apps/core/rbac.py`, `ADMIN_EXCLUDED_PERMISSIONS`.
2. **Guards** — `apps/core/permissions.py`; ten `RolePermissionService` methods
   cut. The finance services split *view* from *action*: `_require_accountant`
   still admits Admin so the disbursement dashboard stays observable, while
   `_require_accountant_action` does not. Same split for the PL fund queue.
3. **Edge** — `apps/admin_ops/middleware.py` refuses any unsafe HTTP method
   from an Admin on a route outside the Admin-owned allow-list, whether it
   arrives as a form POST, an HTMX request, an API call or a hand-edited URL.
   Deny by default: a business route added tomorrow is protected on the day it
   ships. Refusals are audited.

`request.admin_support_view` drives the **"Admin Support View · Read Only"**
banner on every business page. The banner is a courtesy; layer 3 is the rule.

## 4. The three workspaces

| Workspace | Route | What it is |
| --- | --- | --- |
| **Team Plans** | `/admin-ops/team-plans` | Everyone's My Plan, consolidated, read-only |
| **Admin Planning** | `/admin-ops/planning` | Unscheduled platform work — the backlog |
| **Admin My Plan** | `/admin-ops/my-plan` | Admin's own scheduled platform work |

`AdminOperationsWorkItem.scheduled_date is NULL` **is** the Planning/My Plan
split: scheduling an item moves it from one to the other. Critical work skips
the backlog by being created already scheduled for today.

**Team Plans** reads the same `Activity` queryset as `my_plan.services.get`
(same FY filter, same terminal-status exclusion) and derives status and next
action from the canonical `get_activity_status_label_and_class` and
`compute_next_action`. It is not a second copy of the data, and a test asserts
row-for-row parity with the user's own feed. It exposes no mutation at all.

**Admin work is not a field activity.** `AdminOperationsWorkItem` needs no
school, no SSA intervention, no Salesforce ID, no IA verification and no
`ActivityScheduleCostLine`; a test asserts Admin work creates none of them.

## 5. Support, incidents, security

* **Support tickets** — every role can report a problem from any page
  (`/support`, plus a control in the top bar carrying the current route). The
  captured context is route, page, object reference, browser and request id.
  Passwords, tokens, form contents and message text are **refused outright**,
  so a caller that tries to capture them fails loudly rather than leaking
  quietly. One canonical state machine; illegal transitions are rejected.
* **Incidents** — server errors, 404s on registered routes, permission drift,
  SLO breaches, failed and overdue jobs, and browser-reported defects (dead
  buttons, script errors, failed HTMX swaps) all become `SystemIncident` rows.
  Deduplicated on a stable signature: a repeat updates the occurrence count and
  refreshes one notification; a repeat after resolution reopens the incident.
* **Permission drift** is narrow by design. A 403 is only a defect when
  `PAGE_PERMISSIONS` says the role *should* have reached the page. Treating
  every 403 as an incident would have reported the guard rails working.
* **Five failed logins** raise one Admin security incident. The threshold is
  independent of the lockout policy (10), and is read before the lock branch
  resets the counter. The alert carries a masked identifier, streak and lockout
  state — never password material. The public login response is untouched.

## 6. Everything else it plugs into

Notifications, audit, To-Dos and System Health are **reused, not rebuilt**.
Admin-ops notifications deep-link to the exact record (`/admin-ops/incidents/<id>`,
never `/dashboard`), and resolving a condition closes its notifications. Live
updates publish on `transaction.on_commit` through the existing SSE bus —
deliberately not `domain_events.emit`, which would have doubled every audit row
and notification. Seven System Health checks watch operations itself, including
one that fires if Admin ever regains an excluded permission.

## 7. Known gaps

* **Feature-request and release lifecycles** (§24, §25) exist as work-item
  *categories* with the full audit trail, but not as their own approval state
  machines.
* **Admin analytics** (§28) — ticket age, MTTA/MTTR, SLA compliance and
  recurrence trends are not built; the underlying timestamps are all recorded.
* **Break-glass access** (§3) — the sensitive-data limits hold because nothing
  in these surfaces exposes secrets; there is no time-limited elevation flow.
* **Visual verification** — page rendering, structure, permissions and content
  are covered by the test client. Signing in to check the pages visually
  needs credentials, so light/dark and mobile were not eyeballed.
