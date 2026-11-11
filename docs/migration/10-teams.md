# 10. Staff and partner teams, owned by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "Staff and partner team management." Third piece of that brief,
after [sign-in](08-sign-in.md) and [accounts and roles](09-accounts-and-roles.md).

## 10.1 What moved

`platform/proto/edify/identity/v1/teams.proto`, served by
`platform/backend/internal/teams`, behind the normal session check.

**Edify staff** (`StaffTeamService`), a port of
`apps/accounts/supervisor_service.py`:

| Procedure | Existing rule it ports |
|---|---|
| `ListStaff` | the staff roster (`staffPerformance.view`): country roles see the country; anyone else sees themselves and the people who report to them directly |
| `GetSupervisor`, `AssignSupervisor` | `staff.manage`. A CCEO reports to a Program Lead and a Program Lead to a Country Director, checked against the supervisor's working role (the Admin may override). Only the direct line is replaced. Audited `admin.supervisor_reassigned` |
| `GetManagedTeam`, `ConfigureManagedTeam` | the Admin's Role Configuration. A Program Lead's CCEOs (a CCEO keeps one Program Lead, so choosing one moves them; audited `admin.program_lead_team_configured`). Impact Assessment and RVP get chosen staff (`admin.managed_people_configured`). A Country Director's team is the country, automatically |

**A partner organisation's own team** (`PartnerTeamService`), a port of the
partner Users page (`member_logins`, `school_team`, `add_member`,
`remove_member`):

| Procedure | Who | What |
|---|---|---|
| `GetPartnerTeam` | the team's leader, or country staff | members, each one's own login, and the schools the organisation holds (a released hand-over — cancelled, returned, returned to staff — does not count) |
| `AddMember` | whoever manages the roster | staff or volunteer; not audited, as on the web |
| `RemoveMember` | whoever manages the roster | the member's own login is closed (the account lifecycle's `disabled`), their school links are removed, then the member |
| `CreateMemberLogin` | the team's leader | in one transaction: a Partner Field Officer account (no staff profile), linked to the member, audited `partner.member_login_created`; then the invitation or first password, as for any account |
| `ResetMemberPassword` | the team's leader | a temporary password that must be changed; `partner.member_login_password_reset` |
| `SetMemberLoginActive` | the team's leader | `partner.member_login_activated` / `deactivated`; never their own |
| `SetMemberSchools` | the team's leader | a school another member has moves here; unfinished work at a school that moves takes the new person's name (`activity.delivery_contact_name`), delivered work keeps the old one; `partner.school_team_member_set` |

"Leads the team" is the existing `leads_team`: the Admin, the organisation's
own login, or a login of the organisation working as Partner Admin. A
member's Field Officer login does not lead. "Manages the roster" adds the
country roles (Country Director, Impact Assessment, Accountant, BTO, Admin).

Someone working in an acting appointment is refused
(`ACTING_APPOINTMENT_NOT_SUPPORTED`) and sent to the web, until acting
leadership moves.

## 10.2 What still happens in the existing application

A change to reporting lines or managed teams changes the analytics that read
them. Go posts `staff_changed` to the existing relay
(`POST /api/auth/internal/account-events`), and the existing code advances
the accountability analytics revision (`apps.hr.accountability_cache.KEY`),
as it does after a web change. `roles_changed` and `account_deleted` now
advance it too, and creating an account sends `staff_changed`.

Not ported: the existing `PARTNER_ROLE_BRIDGE` demo fallback, which let a
partner login without an organisation borrow one. In Go, a partner login
without an organisation has no team. Also not ported: Impact Assessment's
"overseen" country scope on the roster. Outside the country roles, the roster
is self plus direct reports.

## 10.3 The app

- **Users → Actions** (Admin): **Supervisor** for staff (choices limited to the
  right role, with the rule shown under the field) and **Team** for people
  who manage others (a checklist naming each person's current manager;
  read-only for a Country Director).
- **Team** (Partner Admin, from the web's own `/partner/users` menu link):
  members as cards with their login and school count, one Actions menu per
  person (Give a login, Reset password, Deactivate / Activate login, Schools,
  Remove from team), and Add member in the page header. Menus open below
  their button.

## 10.4 What the database role may do

`platform/deploy/db/identity_roles.sql`, teams section:

- read and replace reporting lines (`staff_supervisor_assignment`: insert and
  delete; `UPDATE(updated_at)` only so a row can be locked while a team is
  rewritten);
- read partners, their hand-overs, schools and districts;
- add, update (user, email) and delete partner members and their school
  links;
- read an activity's partner and contact name, and update the contact name
  only.

The source scan (`internal/dbguard`) allows DELETE only in `internal/teams`
and only on those three link tables. The safety test proves the role still
cannot delete a partner, a hand-over or an activity.
