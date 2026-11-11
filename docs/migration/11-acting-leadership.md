# 11. Acting leadership, owned by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "acting leadership". Fourth piece of that brief, after
[sign-in](08-sign-in.md), [accounts and roles](09-accounts-and-roles.md) and
[teams](10-teams.md). The rules are the existing ones (owner, 2026-10-07):
an acting leader does not have all the privileges of the seat; "their major
task is manage and follow up with the team members."

## 11.1 What moved

`platform/proto/edify/identity/v1/acting.proto`, served by
`platform/backend/internal/acting`, a port of `apps/acting/services.py` on the
existing `acting_assignment` rows.

| Procedure | Existing rule it ports |
|---|---|
| `GetActingBoard` | `board` and `visible_to`: Current, Upcoming (soonest first) and History. Everyone sees their own; a Program Lead their seat's; a Country Director and Human Resources their country's; an Admin all |
| `GetAppointOptions` | `eligible_appointees` and `month_options`. A Program Lead, in their own role, chooses from the CCEOs who report to them; a Country Director from their country's Program Leads; this month and the next eleven |
| `PreviewAppointment` | `preview` and `confirmation_statement`, word for word |
| `Appoint` | `appoint`: one whole calendar month, the seat's row locked, one acting leader per seat and month and one appointment per person and month (the database's unique constraints have the last word). The grant is recorded (`grant_snapshot`) and audited (`acting_assignment.created`). Someone outside the leader's reach is refused, and the attempt kept (`acting_assignment.refused`) |
| `ChangeMonth` | `reschedule`: the appointing leader, before it begins; the first month kept in `revisions`; `acting_assignment.updated` |
| `CancelAppointment` | `cancel` and `may_manage`: the seat's leader, the country's Director for an Acting Program Lead, an Admin for any; access stops on the next request; the record is kept; `acting_assignment.cancelled` |
| `GetAppointment` | `get_visible`: not found unless the caller may read it |
| `SetActingCapacity` | `set_capacity`: the appointee works in the acting capacity or their own role; `acting_capacity.entered` / `.left` |

The policy (who appoints whom, the labels, what is delegated and withheld) is
`apps/acting/policy.py`, exported to
`platform/backend/internal/acting/acting_policy.json` by
`manage.py export_acting_policy`. `apps/acting/tests/test_policy_export.py`
fails when the two differ, and checks the export records what an appointment
made on the web records.

Every write keeps `User.acting_until` in step (`sync_hint`), so the web sees
every appointment made here: one made in the app shows on the web's Acting
Leadership page, and the appointee's web session works in it ("CCEO · Acting
PL · November 2026"), checked in the browser.

## 11.2 The acting capacity of a request

The gateway now reads a person's appointment exactly as the existing
`attach` does, on every request:

- active today, on Kampala's day (`Africa/Nairobi`, the existing
  `TIME_ZONE`), not cancelled;
- still standing (`still_valid`): the appointee holds the role it was made
  from and is not an Admin; the seat and its leader are live and the leader
  still holds the appointing role; a country seat has a country;
- switched on (`in_capacity`), with the request made in the role it was made
  from.

Only then is the request "in an acting capacity". Before this, any
appointment from the day before it started to the day after it ended
refused the person everywhere in Go, even when they had switched back to
their own role.

Modules that have not taken the seat over (schools, cluster leadership,
loans, teams) still refuse a request made in the acting capacity
(`ACTING_APPOINTMENT_NOT_SUPPORTED`), so nothing is decided on the wrong
scope. The person's own account is open: Work as and a new password work
while acting (the web's `PERSONAL_VIEWS`).

Switching to a role one holds leaves the acting capacity, as the web's
`switch_role_view` does. The session carries the appointment
(`Session.acting`).

## 11.3 Differences, each stricter or clearer

- **Entering the capacity from another role.** The web sets the switch and
  says "You are now working as Acting PL", but someone working in another
  role they hold (a CCEO who is also a Project Coordinator) sees nothing
  change. Go also puts the account back in the role the appointment was made
  from, audits the role switch, and returns a token for it.
- **A refused cancellation is kept.** The web writes its refusal inside the
  transaction it then rolls back; Go writes it after.
- **The acts done under an appointment** (the record drawer's list) are not
  served by Go. They are found through the audit payload, which the gateway's
  database role may never read (`TestGatewayRoleCanNeitherWriteNorReadSecrets`).
  That list stays on the web.

## 11.4 What still happens in the existing application

- **Notifications.** Go posts `acting_appointed`, `acting_cancelled` and
  `acting_rescheduled` to the existing relay
  (`POST /api/auth/internal/account-events`, internal key), which sends the
  existing notifications (`apps.acting.services._notify_*`): the appointee,
  and the rest of the seat who should know who is acting.
- **The hourly lifecycle job** (`acting_lifecycle`): reminders three days
  ahead, and the start and end in the audit log. It grants nothing.
- **Working in the seat.** What an acting leader may read and do inside the
  seat is decided page by page on the web (`ActingCapacityMiddleware`); the
  app's screens served by the existing application follow it. Each Go module
  takes the seat over when its rules move.

## 11.5 The app

- **More → Acting Leadership** (the web's own `/acting-leadership` link):
  Current, Upcoming and History, each appointment naming the permanent role
  beside the acting one; one Actions menu per row (Change month, Cancel
  appointment) offering only what the gateway allows; **Appoint Acting PL /
  Acting CD** in the header for whoever may appoint, in two steps as on the
  web (choose, then read and confirm).
- **More → Work as** lists the appointment beside the roles held ("Acting
  Program Lead · November 2026"); the account card reads "CCEO · Acting PL ·
  November 2026" while it is in use.

## 11.6 What the database role may do

`platform/deploy/db/identity_roles.sql`, acting section: read appointments;
insert one; update its month, revisions, reminder, cancellation and
capacity; keep `User.acting_until`. Never a DELETE. The safety test proves
the role can neither delete an appointment nor move it to another seat.
