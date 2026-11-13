# 42. Messages, first piece: the inbox's thread list and unread count, read by Go

Backlog item `messages` (doc 42): Messages for the Next.js web app. The app's
page feed refuses `/messages` for every role (`messages_list` is in neither
`CCEO_PAGES` nor `ROLE_PAGES`, apps/mobile_feed/views.py), so there is no
feed to match: Go answers a contract of its own and is proved against the
existing web page's HTML. It moves in pieces.

| Piece | What moves | State |
|---|---|---|
| 1 | The inbox's list (`/messages`: tabs and their counts, search, sort, rows, pager, which conversation is open) and the top bar's unread count | This document |
| 2 | The open conversation (`thread_detail`) and marking it read: a save, proved in shadow | Backlog `messages-2` |
| 3 | The Next.js `/messages` page on these answers | Backlog `messages-3` |
| 4 | The record gate for activity contexts (outside a country lens) and partner hand-overs for partners, officers and leads | Backlog `messages-4`; handed on until then |
| — | Composing, sending, replying, archiving, starring, drafts, attachments, the context panel | Still the existing application's |

## 42.1 What moved

A new contract, `platform/proto/edify/messaging/v1/messaging.proto`,
`MessagingService`:

- `ListThreads(tab, q, sort, page, thread)`: what
  `apps.frontend.views.message_views.messages_list_view` draws in the page
  header, the filter strip (`pages/messages/index.html`), the thread list
  (`partials/messages/thread_list.html`) and the Message Rules card.
- `GetUnreadCount()`: `services.unread_thread_count`, the top bar's badge.

It is answered by `platform/backend/internal/messaging`, wired in
`internal/server/server.go`. A new contract rather than `GetPage`, so the
mobile app does not gain a page it does not have today.

**Reading the list writes nothing.** The existing page always opens a
conversation (the one asked for, or the first listed) and `thread_detail`
moves the reader's read cursor and marks their messages read. Go's list only
says which conversation is open (`selected_thread_id`); opening it, and the
write, is piece 2. Until then the web page that uses this list must open the
conversation through the existing application, or the conversation stays
unread where the existing page would have marked it read.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("messages")`: every role whose `can_view_page(…, "messages")` is true, exported per role (Cluster Leader and the MFI roles are refused: `NOT_FOUND`, the page's 404). Anyone in an acting capacity is handed on, as every Go page hands them |
| Whose threads | `threads_for_user`: the reader's `MessageParticipant` rows (live, or archived for the Archived tab), each thread's latest message (`ORDER BY created_at`, read last); a thread with no message is not listed |
| Unread | `_is_unread`: the thread has moved (`last_reply_at`), the reader never read it or read it before, and the latest message is not their own |
| Tabs | `TABS` (exported): Unread, Assigned to Me (`recipient_type = to`), Sent (`created_by`), Archived, Partner (a live partner account takes part), Finance (`FINANCE_CONTEXTS`), IA Review (`IA_CONTEXTS`); any other value lists everything. All, Unread and Assigned to Me carry counts, each over the whole inbox |
| Search | `q`, trimmed, a case-folded substring of the subject or the record's label |
| The record gate | `can_access_context`, applied to every row after the filters, as the list applies it (42.2) |
| A row | Sender (a live account's name, else "System"), `avatar_initials`, `last_reply_at` or `updated_at` as `M j, H:i` in Africa/Nairobi (`TIME_ZONE`), subject, the first 90 characters of the latest message, the record's badge (`CONTEXT_LABELS`, else the raw key) and its colour, High (high, urgent) or Low, the star |
| Order | Newest first, a stable sort (equal times keep the statement's order: the same statement Django issues); `sort=oldest` reverses it |
| Pages | `PAGE_SIZE` 8 (exported); a page number read as Python's `int()` (not a number: the first), at least 1, at most the last; the pager drawn past one page: pages 1–3, the last, the current one's neighbours, a gap at the fourth when there are more than five |
| Open conversation | `?thread=` when `_require_thread_access` allows it (the thread exists; the reader takes part, or is the Admin; its record, if it names one, still passes the gate), else none; without `?thread=`, the first row of the page |

## 42.2 The record gate

`can_access_context(user, context_type, context_id)`, in its order:

1. No record kind or id: refused (such a thread is never listed, though a
   participant may still open it by its id).
2. The Admin: allowed. An Accountant: only money kinds and leave. A partner:
   no money kind but disbursements. A kind with no label: refused (so
   `evidence` and `my_plan` threads are listed for the Admin alone).
3. The record, through the same managers (soft-deleted schools, clusters,
   activities and projects are not found; a school by its id or School ID,
   the lowest id first, as `.first()` orders):
   - not found: an IA kind by the IA roles, a workflow stage by its roles
     (`_STAGE_CONTEXTS`), anything else refused;
   - a school, cluster or activity: `RolePermissionService.can_view_record`
     (a Country Director only while `ALLOW_CD_OPERATIONAL_PLANNING`, never a
     Regional Vice President; a country lens reads all; a school in the
     scope's schools, or one nobody holds in a field officer's country
     (`data_gaps.open_to`); a cluster by `cluster_in_scope`;
   - a weekly fund request: its readers' roles, its responsible person, or a
     Programme Lead whose team (supervisees and self, live staff profiles)
     holds it;
   - a leave: its readers' roles, a Programme Lead's team, or the person's
     own;
   - a partner hand-over: Impact Assessment, Project Coordinator, Country
     Director;
   - a project: allowed.

The role sets that were literals inside `can_access_context` are now module
constants (`_IA_UNRESOLVED_ROLES`, `_FUND_REQUEST_READERS`,
`_LEAVE_READERS`, `_PARTNER_ASSIGNMENT_SCOPED`,
`_PARTNER_ASSIGNMENT_READERS`; no behaviour change, apps.messaging's 43
tests pass) and are exported with everything else.

**Handed on.** Two answers need rules Go does not have yet: an activity-kind
record for a reader without a country lens (`can_view_record` for an
Activity: coverage, the supervised-cluster rule, a partner team member's
schools), and a partner hand-over for a partner, officer or Programme Lead
(their Partner Oversight scope). When a reader's inbox holds such a thread,
`ListThreads` answers `UNAVAILABLE` (`SCREEN_UNAVAILABLE`, "Messages open in
the existing application for now.") rather than guess, and the web sends
them to the existing page. That is backlog `messages-4`.

## 42.3 Vocabularies

`python manage.py export_messaging_rules` writes
`internal/messaging/rules.json`: the tabs, page size and Message Rules; the
record kinds, their badges and which kinds each tab and rule reads; the
role sets above; who may open the page and each role's slug
(`get_user_role_slug`), computed per role by the page's own gates;
`ALLOW_CD_OPERATIONAL_PLANNING`, `data_gaps.FIELD_ROLES` and `TIME_ZONE`.
`apps/messaging/test_messaging_rules_export.py` fails when they drift. Words
that live only in templates (the header, the empty state, the sort labels,
the badge colours, the pager's window) are written in Go.

## 42.4 Grants

Appended to `platform/deploy/db/roles.sql` and applied additively to
`edify_gorn_dev` and the integration copy: SELECT on
`messaging_messageparticipant (thread_id, user_id, recipient_type,
last_read_at, archived_at, starred)`, `messaging_messagethread (id, subject,
context_type, context_id, context_label, priority, created_by,
last_reply_at, updated_at, is_system_generated)`, `message (thread_id,
sender_id, body, created_at)` and `leave (id)`. The message body is read for
the 90-character snippet; no attachment, draft, file or linked-items column
is granted. `TestGatewayRoleCanNeitherWriteNorReadSecrets` passes.

## 42.5 Proof

The development seed holds no message at all, and the existing page writes
when it is opened, so the proof runs on a shadow copy only
(`edify_shadow_s22_a`, made from `edify_gorn_dev` by `cmd/shadow/copies.sh`;
the development database was not written). On it, golden threads were filed
straight into the three tables (subjects marked "[Go parity check]"):
78 threads covering each record kind (a school by id and by School ID, a
deleted school, a cluster of the reader's and another, the workflow stages,
an IA kind with no activity, kinds with no label, an unknown kind, no record
at all, fund requests of the reader and of another, a project, a
disbursement, an activity and a partner hand-over for country readers), read
and unread, the reader's own last word, archived, starred, CC'd, high,
urgent and low priority, a system thread from an account that does not
exist, a thread with no message, a partner taking part, a search by record
label, three equal times, and 46 more for the Admin (seven pages).

`internal/messaging/testdata/proof.py` then asks, for each account, 34
questions (the inbox as it opens, each of the eight tabs and an unknown one,
searches with spaces and capitals and one that finds nothing, both sorts and
an unknown one, pages 2, 3, 7, 99, `abc`, 0, −1 and ` 2 `, and seven
`?thread=` values: a thread with no record, an archived one, one on another
page, an activity's, a hand-over's, an unknown kind's, one about a school
not the reader's, and one that does not exist). Go answers first through a
Go-only gateway on the same copy; then the existing page is drawn by
Django's test client and read back from its HTML (tabs and counts, the sort
select, every row's avatar, sender, time, unread dot, subject, snippet,
badge and colour, priority, star and highlight, the empty state, the pager's
summary, pages, gap and next arrow, the open conversation's id, the Message
Rules) and the two compared whole. The badge count is compared with
`unread_thread_count` for each account.

Run over the 29 seed accounts and four more the copy holds (a Partner
Admin, a partner field officer, Human Resources, an Accountant), 20 seconds
apart for the gateway's sign-in limit (`$SP/agent32_run.sh`), its last line
exactly as printed:

    questions 34 users 33 equal 1122 refused_both 0 differing 0

and every account's badge count equal. The inboxes it compared held between
0 and 50 threads (Admin 48, a Programme Lead 50, the officer 35, Impact
Assessment 5, the Country Director 4, the Accountant 4); no reader's inbox
was handed on (the activity and hand-over threads were filed among country
readers and roles Go decides for). The first full run lost 24 accounts to
the sign-in limit (`429`), which is why the pause is there; nothing differed
on the accounts it reached.

## 42.6 Tests and checks

- `internal/messaging/messaging_test.go`: the role gate before any record,
  the unresolved kinds by role, fund requests, leaves, projects, hand-overs
  and the hand-on cases on scripted records, a thread with no record, unread
  at its edges, the avatar's letters, the snippet's length in characters,
  the badge colours, the pager's window (including the template's own
  quirk: page 5 of 9 draws 1 2 3 4 [5] 6 9, with no gap before 9), who may
  open the inbox.
- `internal/integration/messaging_test.go`: a thread filed for an officer by
  a lead is listed unread with its badge, priority and snippet, counted on
  the badge, not unread for its sender, a thread with no record is not
  listed, reading writes no read cursor, and no session is refused.
- `gofmt -l .` (nothing outside `gen/`), `go vet ./...`, `go test -race
  -count=1 ./...`: clean. The integration tests above with
  `TestGatewayRoleCanNeitherWriteNorReadSecrets`: pass. `buf lint`,
  `buf format --diff`, `buf breaking` against the migration branch: clean.
  The web app's `npm run typecheck` with the new generated contract: clean.
- `ruff check`, `ruff format --check`, `bandit -q -r` on the new Python:
  clean. `manage.py test apps.messaging --noinput` (on the agent's own test
  database): 43 tests, OK, the export drift test among them.

## 42.7 What is left, and what looked wrong

- Pieces 2–4 above (backlog `messages-2`, `messages-3`, `messages-4`).
- The mobile app's and the analytics worker's generated stubs for the new
  contract were not generated here (their generators live in
  `platform/mobile`, which this piece does not touch); `make proto` from a
  checkout with the mobile app's packages installed adds them.
- Not proved beyond unit tests, for want of records: a leave thread (the
  seed has no leave), a school nobody holds (the seed's 700 schools are all
  one officer's), Accountants' and partners' role rules beyond the seeded
  accounts, a Programme Lead's team fund request.
- `?tab=` and `?sort=` present but empty: the existing page then marks no tab
  and no sort option; Go reads them as All and Newest.
- A person whose staff profile is soft-deleted: the existing leave rule
  still reads it (a reverse one-to-one uses the base manager), Go's
  principal carries live profiles only. Not reachable with the seed.
- Looked wrong in the existing code: a thread with no record is never listed,
  yet a participant can open it by `?thread=`; the IA kind `evidence` has no
  label, so its threads reach no one but the Admin, although `IA_CONTEXTS`
  names it; the pager skips pages without a gap once past the fourth (page 5
  of 9 shows no "…" before 9).
