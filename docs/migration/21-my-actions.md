# 21. My Actions, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. My Actions is the recipient's
end of a school action: what the reader has been handed, and by when
(`apps.planning.action_workspace.actions_received`).

| Piece | What moves | State |
|---|---|---|
| 1 | My Actions (`/actions/mine`): the tabs and their counts, the queue, its rows and pages | This document |
| — | Acknowledging, starting, blocking and returning an action (`/actions/<id>/<transition>`, `action_service`) | Still the existing application's |
| — | Actions Sent (`/actions/sent`), the sender's end of the same rows | Not moved |

## 21.1 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/myactions` for the path `/actions/mine`, for
someone working in their own role. Go builds the blocks the existing feed
reads from `templates/pages/actions/workspace.html` and
`partials/actions/table.html`.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("my_actions")` and the feed's `can_open_url`: every role but the Cluster Leader. A partner's team member (a login on a partner team it does not lead) is refused it too, as `member_scope.page_withheld` refuses it; a Partner Admin on another organisation's roster is left to the existing application (21.3) |
| The strip | The Project Coordinator's Dashboard strip (`build_workspace`, `partials/_section_nav.html`); nobody else's |
| Whose actions | `actions_received`: those addressed to the reader (`recipient_id`) |
| The line over the queue | Once anything has closed: how many of the resolved actions the record confirmed, and "the rest were closed manually" when not all |
| The tabs | Open (active, less the overdue), Overdue (overdue and escalated), Resolved and All, each with its count over everything handed to the reader; read by the feed as a line of links. `tab` is stripped; one that is not a tab lists everything |
| The queue | The tab's actions, soonest due first (no day last) and the newest first among equals, at most 100 (`actions_received`' own `limit`) |
| A row | School ID (written by the page's script, read empty; a dash with no school), the school's name and district (a live school; "School" and a dash otherwise) linking to its profile, the requested action and its issue's words (`ISSUE_LABELS`, else readable), the sender's name or a dash, the due day and how many days late active work is, the state's pill (`_STATE_TONE`'s words, else the state in title case), read as a pill only when no line sits under it: who closed a resolved action, and why one came back |
| The row's way on | Active work: Open, the action's route, in its Actions menu (a blank route offers nothing; Acknowledge posts, so the feed does not read it). Closed work: View school |
| Pages | Fifty rows (`table_rows_page`), the shared pager read as a panel under the table, carrying the tab |
| Nothing to list | The tabs and "Nothing has been assigned to you." as one panel |

Each role's door and strip, the partner team rule, the tabs, the issue
labels, each state's words, the active, overdue, escalated and resolved
states, the queue's limit, the page size and the query keys the feed drops
are exported to `internal/myactions/rules.json` by `manage.py
export_my_actions_rules`; `apps/planning/test_my_actions_rules_export.py`
fails when the two differ. The limit is read from `actions_received`' own
signature, and the strip is the workspace template rendered for each role
and read by the feed's own reader. The partner team rule
(`decisionlog.PartnerTeamMember`) is shared with the Decision Log, which the
same rule withholds.

## 21.2 Proving it is the same

`cmd/parity -screen page -path /actions/mine` asks the Go-only gateway and
the existing feed the same 14 questions as each account: the page as it
opens; every tab, one padded, one in capitals and one that is not a tab; the
queue's page 2, 999, "abc" and 0; a key the page does not read; and a tab
with a page.

All 29 seed accounts against a gateway with no existing application behind
it. The run's last lines:

    coordinator@edify.org              14 questions, 0 differing

    406 answers compared, 0 differing

Fourteen answers for each account; every role among them opens the page.

The development database holds no school actions, so that run proves the
gate, the Coordinator's strip, the tabs at zero and the empty state. Two
things cover the rest.

**The existing feed's answers over 150 actions, compared in the test
database.** `agent3_actions_golden.py` (kept in the session scratchpad)
points the existing application at the local test database, files 150
actions there (`gpa…`: for eight readers, the seeded officer holding 80 so
the queue pages; senders with and without an account; every state and one
that is not; every issue and one that is not; due days from eight days ago
to four days ahead and none; routes and none; a school that is not on file;
returned reasons, a padded one and one on an active action; resolved by the
record and by hand), asks the feed ten questions as each of 35 accounts (the
29, the RVP, a Regional Programme Lead, HR, the Accountant and both partner
roles), writes the rows and the answers to a file and deletes the rows.
`TestMyActionsMatchesTheExistingFeedOverManyActions`
(`internal/integration/my_actions_test.go`) files the same rows, asks Go the
same questions and compares each answer as a whole message; it is skipped
unless `EDIFY_MY_ACTIONS_GOLDEN` names that file, and on any day but the one
it was made on (lateness is counted from today). It printed:

    my_actions_test.go:144: 350 answers of 35 accounts compared, 0 differing

`TestAPartnersTeamMemberIsRefusedMyActionsAndTheDecisionLog` files a roster
entry for the seeded field officer on a partner whose login is not theirs
and finds both pages refused; the existing feed was asked the same of the
same entry in the test database and answered 404 for My Actions, the
Decision Log and Field Debriefs, for the field officer and for the Partner
Admin.

**Unit tests** (`internal/myactions/page_test.go`) hold the exported doors,
Python's `title()` and `capitalize()` fallbacks, the state pill with and
without lines under it, lateness, the row's way on, a row with no school or
sender on file, the pages and the provenance line.

## 21.3 What is left

- A Partner Admin with a roster entry on a partner whose own login is not
  theirs is a team member unless the partner scope (`resolve_partner_ids`)
  names that partner; Go does not read that scope yet, so it leaves such a
  reader to the existing application rather than guess.
- Actions due on the same day and created at the same instant have no order
  between them.
- Every transition stays the existing application's.

## 21.4 Actions Sent

`/actions/sent` (`actions_sent_view`, `actions_sent`) is the same rows read
from the sender's end, drawn by the same templates, so `internal/myactions`
answers it too: a `side` says which column is the reader's, whose name each
row shows, and the page's words and gates.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("actions_sent")` and the feed's `can_open_url`, exported per role (`sent_roles`): Admin, Country Director, Impact Assessment, Program Lead, Regional Program Lead, Regional Vice President; a partner's team member is refused as on My Actions |
| Whose rows | `sender_id` is the reader; the row shows the recipient's name under "Assigned to" (a recipient with no account reads "—") |
| A row's way on | active work opens its route as the row's own link (the feed reads it as a primary button); overdue work, whose second step is Escalate, puts Open in the Actions menu (Escalate posts, so it never reaches the app); a blank route opens nothing; closed work views the school |
| The rest | the tabs, counts, provenance line, issue and state labels, due words, pager and empty card are My Actions' own, with "You have not sent any school actions yet." |

The view's words, header and empty sentence are written in Go, like My
Actions'. `export_my_actions_rules` now also writes `sent_roles`,
`sent_partner_team_members` and `sent_row_limit`.

Proving it (the coordinator, 2026-11-12):

- All 29 accounts on a gateway with no existing application behind it, the
  same 14 questions as My Actions: `/actions/sent` 406 answers, none
  differing; `/actions/mine` re-run after the change, 406, none differing.
- The development database holds no school actions, so a golden comparison
  carries the rows: the existing feed, unmodified, over 150 synthetic actions
  in the test database (`gpa…`, sent by fourteen accounts, one recipient with
  no account; all removed afterwards), 35 accounts, 10 questions each. 350
  answers, none differing (`TestActionsSentMatchesTheExistingFeedOverManyActions`,
  `EDIFY_ACTIONS_SENT_GOLDEN`). My Actions' own comparison regenerated and
  re-run on the changed code: 350 answers, none differing.

