# 18. The Decision Log, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. The Decision Log is the part of
the tamper-evident audit chain that records a decision somebody made, scoped
to the reader (`apps.audit.decision_log_service`).

| Piece | What moves | State |
|---|---|---|
| 1 | The Decision Log (`/decision-log`): whose decisions, the lookback window, the decision groups, the table and its pages | This document |
| — | Writing the audit chain (`apps.audit.services.log`) | Still the existing application's |

## 18.1 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/decisionlog` for the path `/decision-log`, for
someone working in their own role. The page is the panel
`partials/analytics/panels/decision_log.html` inside the analytics workspace
(`pages/analytics/workspace.html`, `partials/analytics/scope.html`); Go
builds the blocks the existing feed reads from both.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("decision_log")` and the feed's `can_open_url`: every role but the Cluster Leader. A partner's team member (a login on a partner team it does not lead) is refused it too, as `member_scope.page_withheld` refuses it (`partner.go`, shared with My Actions, 21); a Partner Admin on another organisation's roster is left to the existing application, since whether they lead it is the partner scope's, which Go does not read yet. Anyone else is not found, as the feed answers |
| Whose decisions | `decision_log`: Admin and the RVP read every decision; the Country Director and Impact Assessment read those taken by anyone whose live staff profile is in their own country (`_country_filtered`; only their own when no country is on file); everyone else reads only their own (`actor_id`) |
| The decisions | The actions of `DECISION_ACTIONS` (one group's when a known group is asked for), taken in the window, by `actor` when one is asked for; the latest first, at most 200 (`ROW_LIMIT`) |
| The window | `days`: Python's `int()` of it held between 1 and 365, anything else 30. The select offers 7, 30 and 90; a window it does not offer selects none, which the feed reads as the first (7) |
| The groups | A tab rail: All, then Money, People, Programme, Quality, Escalation and Impact, each a link keeping the window. The group asked for is current; an unknown group lights no tab, filters nothing, and still travels as the filter form's hidden value |
| A row | When (`j M, H:i` in Nairobi time), the decision's label and its group, the subject (`_detail`: the first of `staffName`, `schoolName`, `projectName`, `name`, `subject`, `course`, `monthKey` the payload holds, as Python's `str()` writes it; else the decision made, readable; else the subject's id; else a dash), the role that decided (or a dash) and the reason (or a dash) |
| Pages | Fifty rows (`decision_log_log_rows_page`), the shared table pager, read as a panel under the table (16.1) |
| Around it | The document title the workspace's scope carries ("Decision Log · Edify"), Impact Assessment's workspace strip, the decision frame (the confidence's own words sit beside a dot, so the feed reads only its label), the footnote with the count, the scope's name and the window, and the workspace's closing line |

Each role's door, reach, scope name and workspace strip, the groups and their
actions, the labels, the subject keys, the windows, the row cap, the page
size and the query keys the feed drops are exported to
`internal/decisionlog/rules.json` by `manage.py export_decision_log_rules`;
`apps/audit/test_decision_log_rules_export.py` fails when the two differ. The
strip is not restated: the export renders the workspace's tab rail for each
role and reads it with the feed's own reader, so it is exactly what that role
is shown (Impact Assessment's 26 sections; nobody else's). The windows, the
default, the longest window, the row cap and the subject keys were literals
in `decision_log` and `_detail`; they are now module constants there
(`DAY_OPTIONS`, `DEFAULT_DAYS`, `MAX_DAYS`, `ROW_LIMIT`, `DETAIL_KEYS`) so
the export reads them. Nothing they decide changed.

A subject is read from the payload as Python reads it: the stored JSON in its
stored key order, numbers as `int` or `float` (`1234567.0`, `1e-05`,
`100000000000000000000`), lists and objects as `repr()` writes them
(`{'a': 1, 'k': 'v'}`), `True` and `None`, and Python's truth deciding which
key holds anything (`0`, `""`, `[]` do not).

The gateway does not read `audit_log` itself: the audit chain's payloads
(sign-ins, invitations, resets) are not the gateway's to read, and
`TestGatewayRoleCanNeitherWriteNorReadSecrets` refuses them. It reads
`gateway_read.decision_audit` (`platform/deploy/db/decision_log_roles.sql`),
a view in its own schema, owned by a NOLOGIN role no one belongs to: the
decision rows only, and of their payloads only the subject keys and
`decision`, each value as stored. A payload that is not an object reads as
none, which `_detail` treats the same way. The view's action list is the
exported rules', checked by `TestTheDecisionLogViewShowsOnlyDecisions`. It is
a new database object, so production needs the owner's approval at cutover.
(The branch first granted the payload column; the coordinator replaced that
grant with the view when merging, and re-ran parity: 783 answers, none
differing.)

Two Go helpers are shared rather than copied: `closedschools.PyInt`
(`export_decisionlog.go`, Python's `int()` of a query value, including a
number too long to hold) and the archive's pager (`closedschools.PagerPanel`).

## 18.2 Proving it is the same

`cmd/parity -screen page -path /decision-log` asks the Go-only gateway and the
existing feed the same 27 questions as each account: the page as it opens;
windows 7, 30, 90, 45, 1, 0, -3, 400, "abc", " 90 " and "9_0"; every group,
"Other" and "money"; an actor who decided and one who did not; the table's
page 2 and "abc"; a key the page does not read; and a group with a window,
with and without a page.

All 29 seed accounts against a gateway with no existing application behind
it. The run's last lines:

    coordinator@edify.org              27 questions, 0 differing

    783 answers compared, 0 differing

Twenty-seven answers for each account; every role among them opens the page.

The development database holds one decision (a bulk project assignment by
the seeded officer), so that run proves the gate, the three reaches (Admin,
the Country Director and Impact Assessment read it; the officer reads it as
their own; everyone else reads nothing), the strip, the windows, the groups,
the actor filter and the empty state, and nothing about many decisions. Two
things cover the rest.

**The existing feed's answers over 262 decisions, compared in the test
database.** `agent3_decision_golden.py` (kept in the session scratchpad, not
in the repository) points the existing application at the local test
database, files 262 audit rows there (`gpd…`: every decision action and a
non-decision one, 35 hours apart over a year so no row sits within hours of
a window's edge, taken by ten actors including one with no account and one
recorded as nobody, in seven roles including none and an empty one, every
ninth one failed, and 22 payloads: each subject key, empty and falsy values
falling through, the decision, numbers, booleans, lists, nested objects, a
list, a string and no payload at all), asks the feed seventeen questions as
each of 34 accounts (the 29, the RVP, a Regional Programme Lead, HR, the
Accountant and a Partner Admin), writes the rows and the answers to a file
and deletes the rows. `TestTheDecisionLogMatchesTheExistingFeedOverManyDecisions`
(`internal/integration/decision_log_test.go`) files the same rows, asks Go
the same questions and compares each answer as a whole message; it is
skipped unless `EDIFY_DECISION_LOG_GOLDEN` names that file, and skipped when
the file is more than an hour old (the windows move with the clock). It
printed:

    decision_log_test.go:216: 578 answers of 34 accounts compared, 0 differing

That run reaches the 200-row cap, four pages and the pager's arrows, a page
out of range, each reach over many actors (the country readers leaving out
the actor with no account), the actor filter for a global reader and for an
officer reading someone else's id, every label and group, and every payload
shape above. Only `audit_log` rows with ids `gpd…` were written, and none is
left.

**Unit tests** (`internal/decisionlog/page_test.go`) hold what neither
database reaches: an action with no label (Python's `capitalize()`), a group
no action belongs to, Python's `int()` of a window too long to hold, `repr()`
of quotes, backslashes and tabs, and the page drawn for an unknown group.

## 18.3 What is left

- Decisions taken at the same instant have no order between them: the page
  sorts by `created_at` alone, and so does Go.
- `_country_filtered` asks for the reader's staff profile with
  `.only("country").first()`; a reader whose profile names no country reads
  only their own decisions. Go does the same.
- Writing the chain stays the existing application's.
