# 41 (part 2). A person's Staff Activity detail, read by Go

Backlog item `staff-activity-2` (read), continuing
[41-staff-activity.md](41-staff-activity.md).

| Piece | What moves | State |
|---|---|---|
| 2 | A person's detail (`/staff-activity/people/<id>`) for the Country Director and the Admin | This document |
| — | The narrow audit view for weeks with partner hand-overs | Not done: the coordinator's to make (41.1); no view exists |
| — | A Programme Lead's team members' details (covers, acting seats) | Passed on to the existing application |
| — | The export, the follow-up drawers and saves, the heartbeat | Still the existing application's |

## 41.6 The app could not open a person

`/staff-activity/people/<id>` is the part the log's row opens
(`staff_activity_person_view`, `partials/staff_activity/_person_detail.html`).
The feed refused it for everyone: its URL name was neither a native page
nor a part a page loads later, so `read_page` answered 404. It is now in
`apps/mobile_feed/views.py`'s `LATER_PARTS` (one line): the page's own gate
still holds (`require_page_permission("staff_activity")`, `can_open_url`),
and the feed reads the partial as three panels. The app does not link to it
yet (the row's `data-sal-src` is not read); that is the app's to draw.

## 41.7 What moved

`internal/staffactivity/person.go` answers the path for a country reader:

| Part | Existing rule it ports |
|---|---|
| Who may open it | the page's door, exported per role as `doors.<role>.person`; Impact Assessment is refused (`viewer_scope` None, 403 → `PermissionDenied`); anyone else not found |
| Whom | `can_read_person`: the reader's country roster (`country_roster_ids`); anyone else, the reader themselves and an unknown id are refused (403) |
| The person | `_people([id])` (Go's `buildPeople`, the log's row) with `_judge_usage` over that one person, so a role median never exists |
| The top | name and status, title · region · Reports to, initials, Logins / Active time / Meaningful actions / Schools acted on as the reader pairs them, Follow up (Country Director only, never the reader's own row), the close mark |
| The suggestion | the exported reasons (`NO_LOGIN_REASON`, `LOW_ENGAGEMENT_REASON`, `REPEATED_ERRORS_REASON`, lifted to constants), the template's closing sentence |
| Sign-in history | sessions in the period (`at < end` and started or active in it), newest ten (`SESSIONS_SHOWN`), the current one credited with the time since the last beat (`_credit_for`), signed out or timed out, span, active (never above the span) and idle |
| Time by module | every part with time or actions, most time first then name; the actions done there; distinct tasks (`presence_time.working_on`) |
| Meaningful actions | `fold_acts` over the person's audit rows under every id the chain holds for them; the newest twelve (`ACTIONS_SHOWN`); a linked row reads as its label, a plain one as time, label and part |
| Period trend | the bars' labels (a day, a week up to 100 days, a month), sign-in days counted in Kampala time |
| Manager follow-up | the newest five (`FOLLOW_UPS_SHOWN`), the trigger's label linked to the follow-up |

Exported in `rules.json` beside piece 1's rules: the person door, the three
counts shown, the suggestion reasons, and the follow-up triggers' and
statuses' labels.

### When Go passes the reader on

- **A refused request among the twelve actions shown.** Its line names the
  part as the audit row's `reason`. The gateway does not read
  `audit_log.reason`: the column also holds sign-in failure, refresh-token
  reuse and MFA reasons. On the development data every CCEO and Lead has
  refused requests on 13 November (`Unhandled ValueError` /
  `ProgrammingError`), so today, this week and every longer period pass on.
  A coordinator decision would let Go answer them: a narrow view giving
  `left(reason, 80)` for `request_failed` rows only, or a grant of the
  column.
- A school named only in an audit payload, a year the holiday calendar does
  not cover (piece 1's rules).
- Excessive time (never reached for one person; its words stay Python's).
- A Programme Lead: their scope is `team_user_ids` (supervisees, covered
  Leads' officers, an acting seat), not yet ported.

## 41.8 Proving it is the same

On a private copy of the development database (`edify_shadow_s22_base`,
`cmd/shadow/copies.sh base`, then `apply-roles.sh` on that copy only), my
Django (8184, `staff_activity_person` admitted) and a Go-only gateway
(8084). `cmd/parity -screen page -path '/staff-activity/people/{id}' -ids
<the 24 active CCEOs and Leads>` asks 19 questions of each person
(`cmd/parity/page_staff_activity_person.go`): as it opens; each period and
one not offered; days in and out of them (a Sunday, a day to come,
`20261110`, `2026-W46-1`, nonsense, 2025-06-10, 1890); a week, month and
quarter on other days.

All 29 accounts, 24 people, Go-only gateway:

```
coordinator@edify.org              456 questions, 0 differing

13224 answers compared, 2392 differing
```

Every one of the 2392 is a question Go passed on (`go error: unavailable`
against the feed's answer); none differs in content:

- The four Programme Leads, 456 each (1824): their team is the existing
  application's (41.7). The feed answers each a detail or a 403.
- The Country Director and the Admin, 284 each (568): today, this week and
  every longer period (and an unreadable day, which is today) hold refused
  requests (13 November) for every person; 9 November holds 20 people's
  partner hand-overs; 1890 is outside the holiday calendar.
- The other 23 accounts, all 0 differing: Impact Assessment refused (403),
  22 not found.

**What Go itself built:** 344 detail pages (172 for each country reader:
seven questions for all 24 people (8, 10 and 20 November, 2025-06-10, the
week of 2 November, October, the quarter from August) and 9 November for
the four people without hand-overs that day),
all equal to the feed's, plus the 10,488 refusals (403 and 404) of the 23
other accounts.

The pass-on runs, through the same gateway with my Django behind it
(`EDIFY_EXISTING_APP_URL`), the run piece 1 could not make. The log
(`-path /staff-activity`, all 29 accounts, 56 questions for a country
reader):

```
coordinator@edify.org              56 questions, 0 differing

1632 answers compared, 0 differing
```

A person's detail, the seven accounts the page admits (the 22 others are
refused by Go before anything is passed on):

```
pl4@edify.org                      456 questions, 0 differing

3192 answers compared, 0 differing
```

Golden readings (`internal/staffactivity/testdata/person_golden.py` renders
the template with two made-up people and reads it through the feed;
`person_test.go` builds the same people in Go): follow-ups with their
labels, two suggestions, a current and a signed-out session over a total
of twelve, a linked and a plain action, the empty boxes, the Admin without
Follow up, a name with a double space.

## 41.9 Tests

- Unit: the golden readings above; `fold_acts` (an echo renamed by its plain
  row, refusals alone, rows with no request); the trend's labels by day,
  week and month; the address; the follow-up labels and due day.
- Integration (`internal/integration/staff_activity_person_test.go`): an
  officer's day filed in the test database read by the Country Director
  (logins, active time, a signed-out session, two tasks in one part, the
  school action linked, the trend, a follow-up) and by the Admin (no Follow
  up); a refused request then passes the reader on; IA refused, a CCEO not
  found, the director's own id and an unknown id refused, a Programme Lead
  passed on. `TestTheStaffActivityLogCountsAnOfficersDay` expected one header
  action; since page-header-actions merged it is two (Export and the
  Follow-up Queue), so the assertion was corrected.

## 41.10 What is left

- The narrow audit view for hand-over weeks (piece 1) and a decision on
  refused requests' reasons (41.7).
- A Programme Lead's team details (`team_user_ids` with covers and acting
  seats).
- The app drawing a person's detail from the row.
- The export, the follow-up drawers and saves, the heartbeat.
