# Acting Leadership

A leader can hand the operational side of their seat to someone for one
calendar month. Two appointments exist:

| Appointment | Who appoints | Who is appointed | Scope |
| --- | --- | --- | --- |
| Acting Program Lead | A Program Lead | One of the CCEOs who report to them | That Lead's whole team, the Lead included |
| Acting Country Director | A Country Director | A Program Lead of their country | The country |

Nothing about the people changes. `User.roles`, `User.active_role` and the
reporting line (`StaffSupervisorAssignment`) are never written by an
appointment. Sarah the CCEO is Acting PL for October and is a CCEO throughout;
John stays the Program Lead with everything he had.

The code is in `apps/acting` (the engine) and `apps/core/acting.py` (what the
rest of the platform reads). The page is `/acting-leadership`.

## Permanent roles and acting roles

A person's permanent roles are the ones on their account. An acting role is a
record in `acting_assignment`: this person, this acting role, this leader's
seat, this month, appointed by this leader. It is never copied onto the
account, there is no second login, and no duplicate user.

Every list and report that names an appointment shows both: the person, their
permanent role, the acting role, and the month.

## How access is decided

The platform decides access in two places, and an acting appointment goes
through both instead of beside them:

- **the role in use** (`user.active_role`), which page gates, permission keys
  and services read;
- **the scope** (`apps.core.scoping.resolve_user_scope`), which every query is
  filtered by.

`ActingCapacityMiddleware` runs straight after authentication. When the
signed-in person has an appointment that is active today and is working in it,
it attaches an `ActingContext` to the request's user and presents the user in
the acting role, in memory, for that request. From there on:

| Question | Answer in the acting capacity |
| --- | --- |
| Permission keys | The acting role's row of `ROLE_PERMISSIONS`, less the keys the policy withholds (`effective_permissions`) |
| Pages | The acting role's pages in `PAGE_PERMISSIONS`, less the pages the policy withholds (`page_withheld`) |
| Scope | The seat: the appointing Lead's team with the Lead, or the appointing Director's country |
| Changes | Only on pages the policy names as workable; every other write is refused before the view runs |

There is one authorization system. The appointment only supplies the role and
the seat to it, and subtracts.

`User.save()` never writes an acting role: a save made during an acting request
stores the permanent role the database already holds.

### Two capacities, one account

A person with an active appointment works either in the acting capacity or in
their own role, and switches from the account menu, beside the roles they hold.
The choice is kept on the appointment (`in_capacity`), so it survives signing
out. An appointment begins in the acting capacity.

Their own work stays under their own role: their own fund requests, leave,
targets and performance pages are not offered in the acting capacity. Several
of those pages route by the role in use (a Program Lead's advance goes to the
Country Director, a CCEO's to their Lead), so opening them as the acting role
would file the person's own request up the wrong line.

The topbar shows `CCEO · Acting PL · October 2026` while the acting capacity is
in use. The permanent role is always first.

## Scope

The scope is resolved from the seat when the request is made, never from a list
saved at appointment time. Someone who joins or leaves the team mid-month joins
or leaves the acting leader's reach with them. What the seat held on the day of
the appointment is kept in `grant_snapshot` for the record.

**Acting Program Lead.** `supervised_staff_ids` is everyone who reports to the
appointing Lead, plus that Lead, minus the acting leader themself. Their own
schools stay their own (`own_school_ids`), so nobody oversees themselves and
nothing is counted twice. Rosters built from the reporting line find the team
through its Lead (`OversightScope.lead_ids`, `team_lead_user_id`), so the
monitors list the Lead at 280 visits and each CCEO at 560, the acting leader
among them at their own 560.

**Acting Country Director.** Country scope, bounded to the appointing
Director's country, always. An appointment whose seat has no country resolves
no acting capacity at all.

Helpers for code that asks the reporting line directly:

```python
from apps.core.acting import seat_staff_ids, team_lead_user_id, seat_leader_ids

StaffSupervisorAssignment.objects.filter(supervisor_id__in=seat_staff_ids(user))
oversight.program_lead_members(team_lead_user_id(user))
```

Use them on a screen that *reads* a team. Leave a query on the plain reporting
line when it decides who *approves* something: approvals stay with the
permanent line.

## The matrix

`apps/acting/policy.py` is the whole of it: one entry per acting role, naming
what is delegated and what is withheld.

The rule it is written to (owner, 2026-10-07): an acting leader does not have
all the privileges of the seat. Their task is to manage and follow up with the
team members. They read the seat and follow up with its people; a decision
about money, a person's record, a partner organisation or a governed value
stays with the leader who appointed them.

| Capability | Acting PL | Acting CD |
| --- | --- | --- |
| Team planning, execution, calendar | Yes | Yes |
| Team oversight and follow-up ("Send to …") | Yes | Yes |
| Training oversight; each officer's training ceiling | Yes | Read |
| Reviewing the team's completed work, coaching, guidance | Yes | No |
| Schools, projects, priorities | Read; their own as in their own role | Read |
| Partner work: reading it and asking its officer to act | Yes | Yes |
| Answering a withdrawal an officer of the team asked for | Yes | No |
| Holding a partner, granting a partner allowance | No | No |
| Withdrawing, verifying or returning partner work | As in their own role | No |
| Closing schools, assigning clusters | As in their own role | No |
| Editing a school's record | No | No |
| Country-wide calendar events | No | No |
| Performance monitoring | Read | Read |
| Priority and target progress | Read | Read |
| Staff activity and its follow-ups | Yes | Yes |
| Country planning and execution oversight | No | Yes |
| Country analytics, coverage, reports | No | Read |
| Fund approvals, country budget, rate card | No | No |
| Leave approvals, performance reviews, recovery plans | No | No |
| Setting or distributing targets | No | No |
| Users, roles, staff set-up, reporting lines | No | No |
| Planning policy, catalogue, master priorities, policy documents | No | No |
| Verifying delivered work | No | No |
| Appointing or cancelling acting leaders | No | No |
| System administration | No | No |

An Acting PL keeps writing on the pages a CCEO already works, where a Program
Lead reaches no further than a CCEO does (a Lead is read-only at an officer's
schools), and works the team pages the policy names. A decision that sits on
one of those pages beside the follow-up is refused by name (`withheld_views`).

An Acting CD works no page of the country, because a Country Director writes
across the whole country on pages a Program Lead works for one team. Every
page is read, and the appointment carries the follow-up actions the policy
names (`follow_up_views`): "Send to …" from planning, execution and partner
oversight, the follow-ups a director opens and closes with a Lead, a staff
activity follow-up, and raising or answering an escalation. Nothing else on
those pages takes a change from an acting capacity.

Three layers enforce the withheld side, and each is enough by itself:

1. the page is refused (`RolePermissionService.can_view_page`);
2. the permission key is not held (`effective_permissions`);
3. the decision is refused inside the service that makes it
   (`refuse_withheld(principal, FUND_DECISION, …)`), for decisions that are made
   by the reporting line or a role name rather than a key.

On top of those, the middleware refuses any change that is not delegated
(`ActingRole.may_send`), so a role check buried in a service is never the only
thing between an acting leader and a write.

`test_policy.py` also fails when a view named in `follow_up_views` or
`withheld_views` no longer exists, so renaming a view cannot drop it out of
the policy unnoticed.

`apps/acting/tests/test_policy.py` fails when a page or permission the acting
role holds beyond the appointee's is not named as delegated or withheld. A page
given to the Country Director tomorrow is not an Acting Country Director's until
someone decides which it is.

## Lifecycle

```
Upcoming  →  Active  →  Expired
    ↘           ↘
     Cancelled   Cancelled
```

**The state is the dates.** There is no stored status. An appointment is
Upcoming before its first day, Active from 00:00 on that day to the end of its
last, Expired after, and Cancelled when `cancelled_at` is set. Access is read
from that at the moment of each request, so it starts and stops on the month
boundary with nobody doing anything, and no job has to run.

The day is the platform's (`Africa/Nairobi`, `timezone.localdate()`), so October
begins at midnight in Kampala and not three hours later.

An appointment is always one whole calendar month. The month is chosen as a
month; its first and last day are worked out. The table enforces it: the window
starts on the first and ends on the last day of that month.

- **Made ahead.** Any month from this one to eleven ahead.
- **Changed.** Only before it begins, and only its month. The month it was
  first made for is kept in `revisions`. An appointment that has begun is never
  edited: cancel it and make another, and both stay on the record.
- **Cancelled.** By the leader whose seat it is; for an Acting PL also by the
  country's Director; by an administrator for any. Access stops on the next
  request. The row is kept with who cancelled it, when and why.
- **Never deleted.**

One standing acting leader per seat and month, and one standing appointment per
person and month. Both are unique constraints.

The `acting_lifecycle` job (hourly) writes the reminder three days ahead, the
start and the end to the audit log and tells the appointee. It grants and
removes nothing.

An appointment also lapses, without being cancelled, when the people it names
no longer stand: the appointee no longer holds the role they were appointed
from, or the leader whose seat it is has left.

## Audit

Every appointment, change and cancellation is an audit row
(`acting_assignment.created`, `.updated`, `.cancelled`, `.activated`,
`.expired`, `.refused`).

Every act performed in an acting capacity carries the capacity on its audit
row, inside the hashed payload:

```json
"acting": {
  "assignment_id": "…",
  "permanent_role": "CCEO",
  "acting_role": "Program Lead",
  "acting_label": "Acting Program Lead",
  "acting_for": {"name": "John Lead", "…": "…"},
  "appointed_by": {"name": "John Lead", "…": "…"},
  "period": {"start": "2026-10-01", "end": "2026-10-31"}
}
```

`actor_role` is the capacity the act was done in; `acting` is why the actor had
it. An act the same person does in their own role carries no stamp, which is how
delegated work is told from their own. The appointment's record drawer lists
the acts done under it.

## Cost

A person who has never been appointed costs no query: `User.acting_until` (the
last day of their latest standing appointment) is read from the row the request
already loaded. A person with a current appointment costs one indexed lookup a
request. Nothing about an acting capacity is cached between requests, so there
is nothing to invalidate and nothing to go stale.

`acting_until` is a hint. It grants nothing; the appointment and its dates are
read before any acting capacity is given.

## Adding an acting role

1. Add an `ActingRole` entry to `apps/acting/policy.py` and classify every page
   and permission the acting role holds beyond the appointee's.
2. If the seat is a new kind, resolve it in `apps.core.scoping`.
3. Add the eligibility rule in `apps.acting.services.eligible_appointees`.

No other code changes: the middleware, the lifecycle, the audit stamp, the page
and the drawers read the policy entry.

## Not in an acting capacity

- The API reached with a bearer token (`JwtAuthentication`) is always the
  person's own role.
- A person switched to another role they hold (a CCEO who is also a Project
  Coordinator, working as the coordinator) is working in that role.
